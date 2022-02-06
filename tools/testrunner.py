#!/usr/bin/env python3
"""SOF Test Runner
"""

import argparse
import math
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from threading import Timer

# local mode: profile
# server mode: listen
# restore

__SOF_TEST_DIR__ = Path(__file__).parents[1].resolve()

@dataclass()
class TestCaseInfo:
    """Test case information."""

    name: str
    """Test case file name (with extension)"""
    args: str
    """Arguments passed to the test command."""
    env: "dict[str, str]"
    """Environment variables."""
    timeout: float = 0
    """Timeout limit in seconds. 0 means no timeout."""
    skip: bool = False
    """Whether this test case should be skipped."""
    skipreason: str = ''
    """Skip reason."""

class BasicTestRunner:
    """Base class for test runner."""

    def __init__(self, dry_run):
        self._status = 'Idle'
        self._timer = None
        self._case_dir = __SOF_TEST_DIR__.joinpath('test-case')
        self._log_dir = __SOF_TEST_DIR__.joinpath('logs')
        self.dry_run = dry_run

    def runcase(self, case: TestCaseInfo):
        """Run given test case.
        """
        if case.skip:
            self._handle_skip(case.name, case.skipreason)
            return
        proc = None
        filepath = self._case_dir.joinpath(case.name)
        cmd = self.__resolve_cmd(filepath, case.args)
        if not (filepath.name == case.name and filepath.is_file() and cmd is not None):
            self._handle_unknown_case(filepath)
            return
        self._before_cmd_run(cmd)
        if self.dry_run:
            self._handle_exit(0)
            return
        # catch all errors to ensure the whole test flow won't break if one test fails.
        # pylint: disable=W0703
        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                env=case.env,
                cwd=self._case_dir,
                text=True,
                encoding='utf-8',
                errors='replace'
            )
            if math.isfinite(case.timeout) and case.timeout > 0:
                self._timer = Timer(case.timeout, self._handle_timeout, args=[proc, case.timeout])
                self._timer.start()
            while True:
                line = proc.stdout.readline()
                if line:
                    self._handle_output_line(line)
                elif proc.poll() is not None:
                    break
            self._handle_exit(proc.returncode)
        except KeyboardInterrupt:
            self._handle_interrupt(proc)
        except Exception as error:
            self._handle_unknown_exception(error)
        finally:
            proc = None
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None
            self._after_cmd_run(cmd)

    @staticmethod
    def __resolve_cmd(filepath: Path, args: str):
        """Resolve command to run."""
        cmd = os.fspath(filepath) + ' ' + args
        if filepath.suffix in ['.sh', '.bash']:
            return ['bash', '-c', cmd]
        if filepath.suffix == '.py':
            return ['python', '-c', cmd]
        return None

    def _before_cmd_run(self, cmd: "list[str]"):
        """Hook function before command running.
        Typically used to prepare or notify.
        """
        print('=' * 20, file=sys.stderr)
        print('cmd:', *cmd, file=sys.stderr)
        print('=' * 20, file=sys.stderr)

    def _after_cmd_run(self, cmd):
        """Hook function before command running.
        Typically used to cleanup or notify.
        """

    def _handle_unknown_exception(self, error):
        """Unknown exception will be handled here."""
        print('=' * 20, file=sys.stderr)
        print('Unknown exception:', error, file=sys.stderr)
        print('=' * 20, file=sys.stderr)

    def _handle_unknown_case(self, file):
        """If there is a unknown test case, this function will be called."""
        print('=' * 20, file=sys.stderr)
        print('Unknown cases:', file, file=sys.stderr)
        print('=' * 20, file=sys.stderr)

    def _handle_interrupt(self, proc: "subprocess.Popen|None"):
        try:
            if proc is not None and proc.poll() is None:
                proc.terminate()
                self._handle_exit(proc.wait(10), interrupt=True)
        except subprocess.TimeoutExpired:
            self._handle_exit(None, interrupt=True)

    def _handle_timeout(self, proc: "subprocess.Popen|None", timeout):
        if proc is not None and proc.poll() is None:
            proc.terminate()
            self._handle_exit(None, timeout=timeout)

    def _handle_exit(self, exitcode, interrupt=False, timeout=None):
        print('=' * 20, file=sys.stderr)
        if timeout is not None:
            print("Test timed out after", timeout, "seconds", file=sys.stderr)
        if interrupt:
            print("Test has been interrupted!", file=sys.stderr)
        if exitcode:
            print("Exit code:", exitcode, file=sys.stderr)
        print('=' * 20, file=sys.stderr)

    def _handle_skip(self, casename, reason):
        print('=' * 20, file=sys.stderr)
        print("Skip", casename, ":", reason, file=sys.stderr)
        print('=' * 20, file=sys.stderr)

    def _handle_output_line(self, line):
        print(line, end="")

class LocalTestRunner(BasicTestRunner):
    """Local test runner.
    """

    def run(self, data: dict):
        """Run test cases based on the profile data.
        """
        try:
            env = data.get('env', {})
            self._status = 'Running'
            for case in data['cases']:
                caseinfo = TestCaseInfo(
                    case['name'],
                    case.get('args', ''),
                    case.get('timeout', 0),
                    {**env, **case.get('env', {})},
                    case.get('skip', False) is not False,
                    case.get('skip', 'Skipped')
                )
                self.runcase(caseinfo)
        finally:
            self._status = 'Idle'

def parse_cmdline():
    parser = argparse.ArgumentParser(add_help=True, formatter_class=argparse.RawTextHelpFormatter,
        description='A general SOF test runner.')
    parser.add_argument('--version', action='version', version='%(prog)s 1.0')
    parser.add_argument('-p', '--profile', type=str, help="Profile file defined test cases.")
    parser.add_argument('-s', '--serve', type=str, help="Port for server mode.")
    parser.add_argument('--dry-run', action="store_true", help="Don't run any tests, just show what will be done.")

    return parser.parse_args()

def main():
    cmd_args = parse_cmdline()
    if cmd_args.profile is not None:
        runner = LocalTestRunner(cmd_args.dry_run)
        with open(cmd_args.profile) as fp:
            runner.run(json.load(fp))

if __name__ == '__main__':
    main()
