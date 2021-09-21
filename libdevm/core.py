import os
import shutil
import subprocess
from collections import namedtuple
from dataclasses import (
    dataclass
)
from typing import (
    List,
    Optional,
    Callable,
    Tuple,
    Any,
)

import requests as requests
from xtract import xtract

StepExecutionResult = namedtuple("StepExecutionResult", ["return_code", "stdout", "stderr"])


class BuilderException(BaseException):
    def __init__(self, msg):
        self.msg = msg

    def __str__(self):
        return self.msg


class HooksMissing(BuilderException):
    pass


class CurrentHooksNotSet(BuilderException):
    pass


@dataclass
class Hook:
    steps: List[Callable[[Any, Any], StepExecutionResult]]
    description: Optional[str]

    def __call__(self, *args, **kwargs) -> List[StepExecutionResult]:
        r = []
        for step in self.steps:
            r.append(step(*args, **kwargs))

        return r


InstallHook = Hook
UninstallHook = Hook
UpdateHook = Hook
IsUpdatedHook = Hook


@dataclass
class Builder:
    name: str
    description: Optional[str] = ""
    _current_hook: Optional[Hook] = None
    install_hook: Optional[InstallHook] = None
    uninstall_hook: Optional[UninstallHook] = None
    update_hook: Optional[UpdateHook] = None
    is_updated_hook: Optional[IsUpdatedHook] = None

    def download(self, url: str, path: str) -> "Builder":
        self._check_current_hook()

        def step_() -> Tuple[int, bytes, bytes]:
            try:
                r = requests.get(url, stream=True)
                with open(path, 'wb') as f:
                    r.raw.decode_content = True
                    shutil.copyfileobj(r.raw, f)
                    return StepExecutionResult(os.EX_OK, b"downloaded to " + path.encode("utf-8", errors="ignore"), b"")

            except Exception as err:
                return StepExecutionResult(os.EX_SOFTWARE, b"", str(err).encode("utf-8", errors="ignore"))

        self._current_hook.steps.append(step_)
        return self

    def _check_current_hook(self):
        if not self._current_hook:
            raise CurrentHooksNotSet(f"No hook set for {self.name}")

    def extract(self,
                src: str,
                dest: str = None,
                overwrite: bool = False,
                all_: bool = False,
                keep_intermediate: bool = False,
                ):
        self._check_current_hook()

        def step_():
            try:
                xtract(src, dest, overwrite, all_, keep_intermediate)
                stdout = b" ".join((
                    b"extracted",
                    src.encode("utf-8", errors="ignore"),
                    b"to",
                    dest.encode("utf-8", errors="ignore")
                ))
                return StepExecutionResult(os.EX_OK, stdout, b"")
            except Exception as err:
                return StepExecutionResult(os.EX_SOFTWARE, b"", str(err).encode("utf-8", errors="ignore"))

        self._current_hook.steps.append(step_)
        return self

    def rm(self, path: str) -> "Builder":
        self._check_current_hook()

        def step_() -> Tuple[int, bytes, bytes]:
            try:
                shutil.rmtree(path)
                return StepExecutionResult(os.EX_OK, b"removed " + path.encode("utf-8", errors="ignore"), b"")
            except Exception as err:
                return StepExecutionResult(os.EX_SOFTWARE, b"", str(err).encode("utf-8", errors="ignore"))

        self._current_hook.steps.append(step_)
        return self

    def cmd(self, *cmd: str, cwd: str = "") -> "Builder":
        self._check_current_hook()

        def step_() -> Tuple[int, bytes, bytes]:
            nonlocal cwd, cmd
            if not cwd:
                cwd = os.getcwd()
            p = subprocess.run(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            return StepExecutionResult(p.returncode, p.stdout, p.stderr)

        self._current_hook.steps.append(step_)
        return self

    def install(self, description: str = "") -> "Builder":
        if not self.install_hook:
            self.install_hook = InstallHook([], description)
        self._current_hook = self.install_hook
        return self

    def uninstall(self, description: str = "") -> "Builder":
        if not self.uninstall_hook:
            self.uninstall_hook = UninstallHook([], description)
        self._current_hook = self.uninstall_hook
        return self

    def update(self, description: str = "") -> "Builder":
        if not self.update_hook:
            self.update_hook = UpdateHook([], description)
        self._current_hook = self.update_hook
        return self

    def is_updated(self, description: str = "") -> "Builder":
        if not self.is_updated_hook:
            self.is_updated_hook = IsUpdatedHook([], description)
        self._current_hook = self.is_updated_hook
        return self

    def to_recipe(self):
        if not all((self.install_hook, self.uninstall_hook)) and not os.environ.get("DEVM_DEBUG"):
            raise HooksMissing(
                "One of the required hooks are none:\n"
                f"self.install_hook: {self.install_hook}\n"
                f"self.uninstall_hook: {self.uninstall_hook}\n"
            )
        return Recipe(
            name=self.name,
            install_hook=self.install_hook,
            uninstall_hook=self.uninstall_hook,
            update_hook=self.update_hook,
            is_updated_hook=self.is_updated_hook,
        )


@dataclass
class Recipe:
    name: str
    description: Optional[str] = ""
    install_hook: InstallHook = None
    uninstall_hook: UninstallHook = None
    update_hook: UpdateHook = None
    is_updated_hook: Optional[IsUpdatedHook] = None

    def install(self) -> List[Tuple[int, bytes, bytes]]:
        print(f"[*] Installing {self.name}")
        return self.install_hook()

    def update(self) -> List[Tuple[int, bytes, bytes]]:
        print(f"[*] Updating {self.name}")
        return self.update_hook()

    def uninstall(self) -> List[Tuple[int, bytes, bytes]]:
        print(f"[*] Uninstalling {self.name}")
        return self.uninstall_hook()

    def is_updated(self) -> bool:
        return all((r.return_code == 0 for r in self.is_updated_hook()))


def recipe(name: str, description: str = "") -> Builder:
    return Builder(name=name, description=description, )
