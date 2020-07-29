import json
import os.path
import re

from testtools.content import (
    text_content,
)
from testtools.matchers import (
    Contains,
    Equals,
    AfterPreprocessing,
    Always,
    ContainsDict,
)
from testtools import (
    skipIf,
)

from eliot import (
    log_call,
    start_action,
)
from eliot.twisted import (
    DeferredContext,
)
from twisted.internet import defer
from twisted.internet import reactor
from twisted.python import usage
from twisted.python.filepath import (
    FilePath,
)

from allmydata.util.assertutil import precondition
from allmydata.util import fileutil
from allmydata.scripts.common import get_aliases
from allmydata.util.fileutil import abspath_expanduser_unicode
from allmydata.util.encodingutil import unicode_to_argv
from allmydata import uri

from magic_folder.util.eliotutil import (
    log_call_deferred,
)

from ...magic_folder import (
    MagicFolder,
    load_magic_folders,
)
from ... import cli as magic_folder_cli
from ...config import (
    create_global_configuration,
    load_global_configuration,
)

from ...magicfolderdb import (
    get_magicfolderdb,
    SCHEMA_v1,
)

from ..no_network import GridTestMixin
from ..common_util import (
    parse_cli,
    NonASCIIPathMixin,
)
from ..common import (
    AsyncTestCase,
    SyncTestCase,
)
from ..fixtures import (
    SelfConnectedClient,
)
from .common import (
    CLITestMixin,
    cli,
)
from ..common_util import (
    run_magic_folder_cli,
)


class MagicFolderCLITestMixin(CLITestMixin, GridTestMixin, NonASCIIPathMixin):
    def setUp(self):
        GridTestMixin.setUp(self)
        self.alice_nickname = self.unicode_or_fallback(u"Alice\u00F8", u"Alice", io_as_well=True)
        self.bob_nickname = self.unicode_or_fallback(u"Bob\u00F8", u"Bob", io_as_well=True)

    def do_create_magic_folder(self, client_num):
        confpath = FilePath(self.get_clientdir(i=client_num)).child("config")

        if not confpath.exists():
            run_magic_folder_cli(
                "magic-folder", "init",
                "--config", confpath.asBytesMode().path,
                "--listen-endpoint", "tcp:{}".format(4320 + client_num),
                "--node-directory", self.get_clientdir(i=client_num).encode("utf8"),
            )

        folder_dir = FilePath(self.basedir).child(u"magicfolder{}".format(client_num))
        folder_dir.makedirs()

        with start_action(action_type=u"create-magic-folder", client_num=client_num).context():
            d = DeferredContext(
                self.do_cli(
                    "magic-folder", "--debug",
                    "add",
                    b"--author", b"test",
                    folder_dir.asBytesMode().path,
                    client_num=client_num,
                )
            )
        def _done(args):
            (rc, stdout, stderr) = args
            self.assertEqual(rc, 0, stdout + stderr)
            self.assertEqual(stderr, "")
        d.addCallback(_done)
        return d.addActionFinish()

    def do_invite(self, client_num, nickname):
        nickname_arg = unicode_to_argv(nickname)
        action = start_action(
            action_type=u"invite-to-magic-folder",
            client_num=client_num,
            nickname=nickname,
        )
        with action.context():
            d = DeferredContext(
                self.do_cli(
                    "magic-folder",
                    "invite",
                    nickname_arg,
                    client_num=client_num,
                )
            )
        def _done(args):
            (rc, stdout, stderr) = args
            self.assertEqual(rc, 0, stdout + stderr)
            return (rc, stdout, stderr)
        d.addCallback(_done)
        return d.addActionFinish()

    def do_list(self, client_num, json=False):
        args = ("magic-folder", "list",)
        if json:
            args = args + ("--json",)
        d = self.do_cli(*args, client_num=client_num)
        def _done(args):
            (rc, stdout, stderr) = args
            return (rc, stdout, stderr)
        d.addCallback(_done)
        return d

    def do_join(self, client_num, local_dir, invite_code):
        confpath = FilePath(self.get_clientdir(i=client_num)).child("config")

        if not confpath.exists():
            run_magic_folder_cli(
                "magic-folder", "init",
                "--config", confpath.asBytesMode().path,
                "--listen-endpoint", "tcp:{}".format(4320 + client_num),
                "--node-directory", self.get_clientdir(i=client_num).encode("utf8"),
            )

        action = start_action(
            action_type=u"join-magic-folder",
            client_num=client_num,
            local_dir=local_dir,
            invite_code=invite_code,
        )
        with action.context():
            precondition(isinstance(local_dir, unicode), local_dir=local_dir)
            precondition(isinstance(invite_code, str), invite_code=invite_code)
            local_dir_arg = unicode_to_argv(local_dir)
            d = DeferredContext(
                self.do_cli(
                    "magic-folder",
                    "join",
                    "--author", "test-dummy",
                    invite_code,
                    local_dir_arg,
                    client_num=client_num,
                )
            )
        def _done(args):
            (rc, stdout, stderr) = args
            self.assertEqual(rc, 0, stdout + stderr)
            self.assertEqual(stdout, "")
            self.assertEqual(stderr, "")
            return (rc, stdout, stderr)
        d.addCallback(_done)
        return d.addActionFinish()

    def do_leave(self, client_num):
        d = self.do_cli("magic-folder", "leave", client_num=client_num)
        def _done(args):
            (rc, stdout, stderr) = args
            self.assertEqual(rc, 0, stdout + stderr)
            return (rc, stdout, stderr)
        d.addCallback(_done)
        return d

    def check_joined_config(self, client_num, upload_dircap):
        """Tests that our collective directory has the readonly cap of
        our upload directory.
        """
        action = start_action(action_type=u"check-joined-config")
        with action.context():
            collective_readonly_cap = self.get_caps_from_files(client_num)[0]
            d = DeferredContext(
                self.do_cli(
                    "ls", "--json",
                    collective_readonly_cap,
                    client_num=client_num,
                )
            )
        def _done(args):
            (rc, stdout, stderr) = args
            self.assertEqual(rc, 0, stdout + stderr)
            return (rc, stdout, stderr)
        d.addCallback(_done)
        def test_joined_magic_folder(args):
            (rc, stdout, stderr) = args
            readonly_cap = unicode(uri.from_string(upload_dircap).get_readonly().to_string(), 'utf-8')
            s = re.search(readonly_cap, stdout)
            self.assertTrue(s is not None)
            return None
        d.addCallback(test_joined_magic_folder)
        return d.addActionFinish()

    def get_caps_from_files(self, client_num):
        config = load_global_configuration(
            FilePath(self.get_clientdir(i=client_num)).child("config")
        )
        folder_config = config.get_magic_folder("default")
        return folder_config.collective_dircap, folder_config.upload_dircap

    def create_invite_join_magic_folder(self, nickname, local_dir):
        local_dir_arg = unicode_to_argv(local_dir)
        client_path = FilePath(self.get_clientdir())
        config = client_path.child("config")

        # the --debug means we get real exceptions on failures
        d = self.do_cli(
            "magic-folder", "--debug", "init",
            "--config", config.asBytesMode().path,
            "--listen-endpoint", "tcp:4319",
            "--node-directory", client_path.asBytesMode().path,
        )

        def _done_init(args):
            (rc, stdout, stderr) = args
            self.assertEqual(rc, 0, stdout + stderr)
            return self.do_cli(
                b"magic-folder",
                b"--config", config.asBytesMode().path,
                b"--debug",
                b"--author", b"test",
                b"add", local_dir_arg)
        d.addCallback(_done_init)

        def _done_add(args):
            (rc, stdout, stderr) = args
            self.assertEqual(rc, 0, stdout + stderr)

            client = self.get_client()
            self.collective_dircap, self.upload_dircap = self.get_caps_from_files(0)
            self.collective_dirnode = client.create_node_from_uri(self.collective_dircap)
            self.upload_dirnode     = client.create_node_from_uri(self.upload_dircap)
        d.addCallback(_done_add)

        d.addCallback(lambda ign: self.check_joined_config(0, self.upload_dircap))
        return d

    # XXX should probably just be "tearDown"...
    @log_call_deferred(action_type=u"test:cli:magic-folder:cleanup")
    def cleanup(self, res):
        d = DeferredContext(defer.succeed(None))
        def _clean(ign):
            return self.magicfolder.disownServiceParent()

        d.addCallback(_clean)
        d.addCallback(lambda ign: res)
        return d.result

    def init_magicfolder(self, client_num, upload_dircap, collective_dircap, local_magic_dir, clock):
        dbfile = FilePath(self.get_clientdir(i=client_num)).child("legacy_state.sqlite")
        collective = uri.from_string(collective_dircap)
        db = get_magicfolderdb(dbfile, create_version=(SCHEMA_v1, 1))
        if db is None:
            self.fail("Unable to create the db: {}".format(dbfile))

        client = self.get_client(client_num)
        name='default'

        magicfolder = MagicFolder(
            client=client,
            upload_dircap=upload_dircap,
            collective_dircap=collective.get_readonly().to_string(),
            local_path_u=local_magic_dir,
            db=db,
            umask=0o077,
            name=name,
            clock=clock,
            uploader_delay=0.2,
            downloader_delay=0,
        )

        magicfolder.setServiceParent(self.get_client(client_num))
        magicfolder.ready()
        return magicfolder


class ListMagicFolder(AsyncTestCase):
    """
    Tests for the command-line interface ``magic-folder list``.
    """
    @defer.inlineCallbacks
    def setUp(self):
        """
        Create a Tahoe-LAFS node which can contain some magic folder configuration
        and run it.
        """
        yield super(ListMagicFolder, self).setUp()
        self.client_fixture = SelfConnectedClient(reactor)
        yield self.client_fixture.use_on(self)

        self.tempdir = self.client_fixture.tempdir
        self.node_directory = self.client_fixture.node_directory
        self.config_dir = FilePath(self.mktemp())
        create_global_configuration(self.config_dir, u"tcp:4321", self.node_directory)

    @defer.inlineCallbacks
    def test_list_none(self):
        """
        When there are no Magic Folders at all, the output of the list command
        reports this.
        """
        outcome = yield cli(
            self.config_dir,
            [b"list"],
        )
        self.assertThat(outcome.stdout, Contains(u"No magic-folders"))

    @defer.inlineCallbacks
    def test_list_none_json(self):
        """
        When there are no Magic Folders at all, the output of the list command
        reports this in JSON format if given ``--json``.
        """
        outcome = yield cli(
            self.config_dir,
            [b"list", b"--json"],
        )
        self.assertThat(outcome.stdout, AfterPreprocessing(json.loads, Equals({})))

    @defer.inlineCallbacks
    def test_list_some(self):
        """
        When there are Magic Folders, the output of the list command describes
        them.
        """
        # Get a magic folder.
        folder_path = self.tempdir.child(u"magic-folder")
        folder_path.makedirs()

        outcome = yield cli(
            self.config_dir, [
                b"add",
                b"--name", b"list-some-folder",
                b"--author", b"alice",
                folder_path.asBytesMode().path,
            ],
        )
        self.assertThat(
            outcome.succeeded(),
            Equals(True),
        )

        outcome = yield cli(
            self.config_dir,
            [b"list"],
        )
        self.expectThat(outcome.stdout, Contains(b"list-some-folder"))
        self.expectThat(outcome.stdout, Contains(folder_path.path))

    @defer.inlineCallbacks
    def test_list_some_json(self):
        """
        When there are Magic Folders, the output of the list command describes
        them in JSON format if given ``--json``.
        """
        # Get a magic folder.
        folder_path = self.tempdir.child(u"magic-folder")
        folder_path.makedirs()

        outcome = yield cli(
            self.config_dir, [
                b"add",
                b"--author", b"test",
                b"--name", b"list-some-json-folder",
                folder_path.asBytesMode().path,
            ],
        )
        self.assertThat(
            outcome.succeeded(),
            Equals(True),
        )
        outcome = yield cli(
            self.config_dir,
            [b"list", b"--json"],
        )
        self.expectThat(
            outcome.stdout,
            AfterPreprocessing(
                json.loads,
                ContainsDict({
                    u"list-some-json-folder": ContainsDict({
                        u"magic_path": Equals(folder_path.path),
                        u"poll_interval": Equals(60),
                        u"is_admin": Equals(True),
                    }),
                }),
            ),
        )


def addOutcomeDetails(testcase, outcome):
    testcase.addDetail(
        u"stdout",
        text_content(outcome.stdout),
    )
    testcase.addDetail(
        u"stderr",
        text_content(outcome.stderr),
    )
    testcase.addDetail(
        u"code",
        text_content(unicode(outcome.code)),
    )


class CreateMagicFolder(AsyncTestCase):
    @defer.inlineCallbacks
    def setUp(self):
        """
        Create a Tahoe-LAFS node which can contain some magic folder configuration
        and run it.
        """
        yield super(CreateMagicFolder, self).setUp()
        self.client_fixture = SelfConnectedClient(reactor)
        yield self.client_fixture.use_on(self)

        self.tempdir = self.client_fixture.tempdir
        self.config_dir = FilePath(self.mktemp())
        create_global_configuration(
            self.config_dir,
            u"tcp:4321",
            self.client_fixture.node_directory,
        )

    @defer.inlineCallbacks
    def test_add_magic_folder(self):
        """
        Create a new magic folder with a nickname and local directory so
        that this folder is also invited and joined with the given nickname.
        """
        # Get a magic folder.
        magic_folder = self.tempdir.child(u"magic-folder")
        magic_folder.makedirs()

        outcome = yield cli(
            self.config_dir, [
                b"add",
                b"--author", b"test",
                magic_folder.asBytesMode().path,
            ],
        )
        self.assertThat(
            outcome.succeeded(),
            Equals(True),
        )

    @defer.inlineCallbacks
    def test_create_duplicate_name(self):
        """
        Create a magic folder and if that succeeds, then create another
        magic folder with the same name and check if this results in an
        error.
        """
        # Get a magic folder.
        magic_folder = self.tempdir.child(u"magic-folder")
        magic_folder.makedirs()

        outcome = yield cli(
            self.config_dir, [
                b"add",
                b"--name", b"foo",
                b"--author", b"test",
                magic_folder.asBytesMode().path,
            ],
        )

        self.assertThat(
            outcome.succeeded(),
            Always(),
        )

        outcome = yield cli(
            self.config_dir, [
                b"add",
                b"--name", b"foo",
                b"--author", b"test",
                magic_folder.asBytesMode().path,
            ],
        )

        self.assertThat(
            outcome.succeeded(),
            Equals(False),
        )
        self.assertIn(
            "Already have a magic-folder named 'foo'",
            outcome.stderr
        )

    @defer.inlineCallbacks
    def test_add_leave_folder(self):
        """
        Create a magic folder and then leave the folder and check
        whether it was successful.
        """
        # Get a magic folder.
        magic_folder = self.tempdir.child(u"magic-folder")
        magic_folder.makedirs()

        outcome = yield cli(
            self.config_dir, [
                b"add",
                b"--name", b"foo",
                b"--author", b"test",
                magic_folder.asBytesMode().path,
            ],
        )

        self.assertThat(
            outcome.succeeded(),
            Equals(True),
        )

        outcome = yield cli(
            self.config_dir, [
                b"leave",
                b"--name", b"foo",
                b"--really-delete-write-capability",
            ],
        )

        self.assertThat(
            outcome.succeeded(),
            Equals(True),
        )

    @defer.inlineCallbacks
    def test_leave_wrong_folder(self):
        """
        Create a magic folder with a specified name and then invoke
        the leave command with a different specified name. This should
        result in a failure.
        """
        # Get a magic folder.
        magic_folder = self.tempdir.child(u"magic-folder")
        magic_folder.makedirs()

        outcome = yield cli(
            self.config_dir, [
                b"add",
                b"--author", b"test",
                b"--name", b"foo",
                magic_folder.asBytesMode().path,
            ],
        )

        self.assertThat(
            outcome.succeeded(),
            Equals(True),
        )

        outcome = yield cli(
            self.config_dir, [
                b"leave",
                b"--name", b"bar",
            ],
        )

        self.assertThat(
            outcome.succeeded(),
            Equals(False),
        )
        self.assertIn(
            "No such magic-folder 'bar'",
            outcome.stderr
        )

    @defer.inlineCallbacks
    def test_leave_no_folder(self):
        """
        Create a magic folder and then leave the folder. Leaving it again
        should result in an error.
        """
        # Get a magic folder.
        magic_folder = self.tempdir.child(u"magic-folder")
        magic_folder.makedirs()

        outcome = yield cli(
            self.config_dir, [
                b"add",
                b"--name", b"foo",
                b"--author", b"alice",
                magic_folder.asBytesMode().path,
            ],
        )

        self.assertThat(
            outcome.succeeded(),
            Equals(True),
        )

        outcome = yield cli(
            self.config_dir, [
                b"leave",
                b"--name", b"foo",
                b"--really-delete-write-capability",
            ],
        )

        self.assertThat(
            outcome.succeeded(),
            Equals(True),
        )

        outcome = yield cli(
            self.config_dir, [
                b"leave",
                b"--name", b"foo",
            ],
        )

        self.assertThat(
            outcome.succeeded(),
            Equals(False),
        )
        self.assertIn(
            "No such magic-folder 'foo'",
            outcome.stderr
        )

    @defer.inlineCallbacks
    def test_leave_no_folders_at_all(self):
        """
        Leave a non-existant magic folder. This should result in
        an error.
        """
        outcome = yield cli(
            self.config_dir, [
                b"leave",
                b"--name", b"foo",
            ],
        )

        self.assertThat(
            outcome.succeeded(),
            Equals(False),
        )
        self.assertIn(
            "No such magic-folder 'foo'",
            outcome.stderr
        )

    @defer.inlineCallbacks
    def test_add_invite_join(self):
        """
        Create a magic folder and create an invite code. We create a
        second magic-folder instance and use the code to join.
        """
        # Get a magic folder.
        basedir = self.tempdir.child(u"magic-folder")
        local_dir = basedir.child(u"alice")
        local_dir.makedirs()

        outcome = yield cli(
            self.config_dir, [
                b"add",
                b"--author", b"alice",
                local_dir.asBytesMode().path,
            ],
        )

        self.assertThat(
            outcome.succeeded(),
            Equals(True),
        )

        # create invite code for bob
        outcome = yield cli(
            self.config_dir, [
                b"invite",
                b"bob",
            ],
        )

        self.assertThat(
            outcome.succeeded(),
            Equals(True),
        )

        # capture the invite code from stdout
        invite_code = outcome.stdout.strip().encode("utf8")

        # create a directory for Bob
        mf_bob = basedir.child(u"bob")
        mf_bob.makedirs()
        # join
        outcome = yield cli(
            self.config_dir, [
                b"join",
                b"--name", b"other",
                b"--author", b"test-dummy",
                invite_code,
                mf_bob.asBytesMode().path,
            ],
        )

        self.assertThat(
            outcome.succeeded(),
            Equals(True),
        )

    @defer.inlineCallbacks
    def test_join_leave_join(self):
        """
        Create a magic folder, create an invite code, use the
        code to join, leave the folder and then join again with
        the same invite code.
        """
        # Get a magic folder.
        basedir = self.tempdir.child(u"magic-folder")
        basedir.makedirs()

        outcome = yield cli(
            self.config_dir, [
                b"add",
                b"--author", b"test",
                basedir.asBytesMode().path,
            ],
        )

        self.assertThat(
            outcome.succeeded(),
            Equals(True),
        )

        # create invite code for bob
        outcome = yield cli(
            self.config_dir, [
                b"invite",
                b"bob",
            ],
        )

        self.assertThat(
            outcome.succeeded(),
            Equals(True),
        )

        # capture the invite code from stdout
        invite_code = outcome.stdout.strip().encode("utf8")

        # create a directory for Bob
        mf_bob = basedir.child(u"bob")
        mf_bob.makedirs()

        # join
        outcome = yield cli(
            self.config_dir, [
                b"join",
                b"--author", b"test-dummy",
                b"--name", b"bob-folder",
                invite_code,
                mf_bob.asBytesMode().path,
            ],
        )
        self.assertThat(
            outcome.succeeded(),
            Equals(True),
        )

        # leave
        outcome = yield cli(
            self.config_dir, [
                b"leave",
                b"--name", b"bob-folder",
            ],
        )

        self.assertThat(
            outcome.succeeded(),
            Equals(True),
        )

        # join (again)
        outcome = yield cli(
            self.config_dir, [
                b"join",
                b"--author", b"test-dummy",
                b"--name", b"bob-folder",
                invite_code,
                mf_bob.asBytesMode().path,
            ],
        )

        self.assertThat(
            outcome.succeeded(),
            Equals(True),
        )

    def test_help_synopsis(self):
        """
        Test if synonsis is defined for the help switch.
        """
        self.basedir = "cli/MagicFolder/help_synopsis"
        os.makedirs(self.basedir)

        o = magic_folder_cli.AddOptions()
        o.parent = magic_folder_cli.MagicFolderCommand()
        o.parent.getSynopsis()

    def test_no_config_directory(self):
        """
        Running a command without --config fails
        """
        o = magic_folder_cli.InviteOptions()
        o.parent = magic_folder_cli.MagicFolderCommand()

        try:
            o.parent.parseOptions(["invite", "nickname"])
        except usage.UsageError as e:
            self.assertIn("doesn't exist", str(e))
        else:
            self.fail("expected UsageError")

    def test_config_directory_is_file(self):
        """
        Using --config with a file is an error
        """
        o = magic_folder_cli.MagicFolderCommand()
        nodefile = self.mktemp()
        with open(nodefile, "w") as f:
            f.write("dummy\n")

        try:
            o.parseOptions(["--config", nodefile, "invite", "nickname"])
        except usage.UsageError as e:
            self.assertIn("Unable to load configuration", str(e))
        else:
            self.fail("expected UsageError")

    def test_config_directory_empty(self):
        """
        A directory that is empty isn't valid for --config
        """
        o = magic_folder_cli.MagicFolderCommand()
        nodedir = self.mktemp()
        os.mkdir(nodedir)

        try:
            o.parseOptions(["--config", nodedir, "invite", "nickname"])
        except usage.UsageError as e:
            self.assertIn("Unable to load configuration", str(e))
        else:
            self.fail("expected UsageError")

    @defer.inlineCallbacks
    @skipIf(sys.platform != "linux2")
    def test_join_author_user(self):
        """
        The CLI will use USER from the environment
        """
        basedir = self.tempdir.child(u"join-author-user")
        basedir.makedirs()

        outcome = yield cli(
            self.config_dir, [
                b"add",
                basedir.asBytesMode().path,
            ],
        )
        self.assertThat(
            outcome.succeeded(),
            Equals(True),
        )
        # create invite code for bob
        outcome = yield cli(
            self.config_dir, [
                b"invite",
                b"bob",
            ],
        )
        self.assertThat(
            outcome.succeeded(),
            Equals(True),
        )

        # capture the invite code from stdout
        invite_code = outcome.stdout.strip().encode("utf8")

        # create a directory for Bob
        mf_bob = basedir.child(u"bob")
        mf_bob.makedirs()

        # join
        # we don't pass --author so should get author from $USER
        olduser = os.environ.get("USER", None)
        os.environ["USER"] = "bob_from_user"
        try:
            outcome = yield cli(
                self.config_dir, [
                    b"join",
                    # no --author, so it should come from USER env-var
                    b"--name", b"other",
                    invite_code,
                    mf_bob.asBytesMode().path,
                ],
            )
        finally:
            if olduser is None:
                del os.environ["USER"]
            else:
                os.environ["USER"] = olduser

        self.assertThat(
            outcome.succeeded(),
            Equals(True),
        )


    @defer.inlineCallbacks
    def test_join_twice_failure(self):
        """
        Create a magic folder, create an invite code, use it to join and then
        join again with the same code without leaving. This should result
        in an error.
        """
        # Get a magic folder.
        basedir = self.tempdir.child(u"magic-folder")
        local_dir = basedir.child(u"alice")
        local_dir.makedirs()

        outcome = yield cli(
            self.config_dir, [
                b"add",
                b"--author", b"test",
                local_dir.asBytesMode().path,
            ],
        )

        self.assertThat(
            outcome.succeeded(),
            Equals(True),
        )

        # create invite code for bob
        outcome = yield cli(
            self.config_dir, [
                b"invite",
                b"bob",
            ],
        )

        self.assertThat(
            outcome.succeeded(),
            Equals(True),
        )

        # capture the invite code from stdout
        invite_code = outcome.stdout.strip().encode("utf8")

        # create a directory for Bob
        mf_bob = basedir.child(u"bob")
        mf_bob.makedirs()

        # join
        outcome = yield cli(
            self.config_dir, [
                b"join",
                b"--author", b"test-dummy",
                b"--name", b"other",
                invite_code,
                mf_bob.asBytesMode().path,
            ],
        )

        self.assertThat(
            outcome.succeeded(),
            Equals(True),
        )

        # join (again)
        outcome = yield cli(
            self.config_dir, [
                b"join",
                b"--author", b"test-dummy",
                b"--name", b"other",
                invite_code,
                mf_bob.asBytesMode().path,
            ],
        )

        self.assertThat(
            outcome.succeeded(),
            Equals(False),
        )

        self.assertIn(
            "This client already has a magic-folder named 'other'",
            outcome.stderr
        )


class CreateErrors(SyncTestCase):

    def setUp(self):
        super(CreateErrors, self).setUp()
        self.temp = FilePath(self.mktemp())
        self.temp.makedirs()

    def test_poll_interval(self):
        with self.assertRaises(usage.UsageError) as ctx:
            parse_cli(
                "add",
                "--author", "test",
                "--poll-interval=frog",
                self.temp.path
            )
        self.assertEqual(str(ctx.exception), "--poll-interval must be a positive integer")


class JoinErrors(AsyncTestCase):
    def test_poll_interval(self):
        with self.assertRaises(usage.UsageError) as ctx:
            parse_cli("join", "--author", "test-dummy", "--poll-interval=frog", "code", "localdir")
        self.assertEqual(str(ctx.exception), "--poll-interval must be a positive integer")

        with self.assertRaises(usage.UsageError) as ctx:
            parse_cli("join", "--author", "test-dummy", "--poll-interval=-2", "code", "localdir")
        self.assertEqual(str(ctx.exception), "--poll-interval must be a positive integer")
