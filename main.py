"""Terminal entry point — interactive ReAct agent with persistent input history.

Improvements over the previous bare-bones REPL:

- Persistent input history in ``~/.research_copilot_history`` (readline).
- Multi-line input: backslash continuation or paste; press Enter on an empty
  line to submit.
- Tab completion for common commands (``exit``, ``quit``, ``reset``, ``help``,
  ``clear``, ``/config``, ``/route``, ``/model``).
- Friendlier startup banner with active model + route hints.
- ``/config`` prints the active configuration; ``/route`` shows the most
  recent routing decision.
"""

from __future__ import annotations

import atexit
import logging
import os
import readline
import sys
from pathlib import Path

from config_loader import load_project_config

# Load config.yaml before importing config-dependent modules.
load_project_config(Path(__file__).resolve().parent)

from agent.core import Agent  # noqa: E402
from config import MAX_MEMORY_TURNS, MAX_STEPS, validate_config  # noqa: E402
from llm.prompts import build_system_prompt  # noqa: E402
from tools.registry import ToolRegistry  # noqa: E402


HISTORY_FILE = Path(
    os.environ.get("RESEARCH_COPILOT_HISTORY")
    or (Path.home() / ".research_copilot_history")
)
HISTORY_LIMIT = 500
BANNER = r"""
+-------------------------------------------------------+
|                                                       |
|   Research Copilot Agent  (terminal)                  |
|                                                       |
|   输入问题后回车开始，回车空行提交多行输入。           |
|   Type your question and press Enter.                 |
|                                                       |
|   Commands:  /help    show command list                |
|              /config  show active config               |
|              /route   show last routing decision       |
|              /reset   start a new conversation        |
|              /quit    exit                            |
|                                                       |
+-------------------------------------------------------+
"""


def _setup_readline() -> None:
    """Enable persistent history and tab completion for the REPL."""
    try:
        readline.parse_and_bind("tab: complete")
        readline.parse_and_bind("set editing-mode emacs")
    except Exception:
        return  # readline not available on Windows without pyreadline
    try:
        if HISTORY_FILE.exists():
            readline.read_history_file(str(HISTORY_FILE))
    except OSError:
        pass
    readline.set_history_length(HISTORY_LIMIT)
    atexit.register(_save_history)


def _save_history() -> None:
    try:
        HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
        readline.write_history_file(str(HISTORY_FILE))
    except OSError:
        pass


COMMANDS = ("/help", "/config", "/route", "/reset", "/quit", "/exit", "/clear")


def _complete(text: str, state: int):
    if state == 0:
        if not text.startswith("/"):
            return None
        _complete.matches = [c for c in COMMANDS if c.startswith(text)]
    if state < len(_complete.matches):
        return _complete.matches[state]
    return None


if hasattr(readline, "set_completer"):
    readline.set_completer(_complete)


def _read_multiline() -> str:
    """Read a multi-line input, ended by an empty line.

    Backslash at end of line continues onto the next line (classical REPL
    convention).  Press Enter on an empty line to submit.
    """
    lines = []
    while True:
        try:
            raw = input("... " if lines else "You> ")
        except (EOFError, KeyboardInterrupt):
            print()
            return ""
        # Backslash continuation: keep reading until line doesn't end with "\\".
        while raw.endswith("\\"):
            raw = raw[:-1]
            try:
                raw += input("... ")
            except (EOFError, KeyboardInterrupt):
                raw = raw.rstrip("\\")
                break
        if raw.strip() == "":
            if lines:
                break
            # Leading blank lines are ignored.
            continue
        lines.append(raw)
    return "\n".join(lines).strip()


def _print_banner(agent: Agent) -> None:
    """Print startup banner with model routing information.

    A warm-up route is performed once and cached; the banner displays the
    result so the user sees which model will be used by default."""
    decision = agent.model_router.route("(warmup)")
    print(BANNER)
    print(
        f"  模型路由 → {decision.route_name} → {decision.model_name}"
        f"（base: {decision.base_url or 'default'}）"
    )
    print(
        f"  ReAct 上限: {MAX_STEPS} 步 · 上下文保留: {MAX_MEMORY_TURNS} 轮\n"
    )


def _print_help() -> None:
    print(
        """可用命令:
  /help     显示本帮助
  /config   打印当前生效的配置（模型 / 检索模式 / KB 路径）
  /route    显示最近一次路由决策（模型名 + 原因 + confidence）
  /reset    重新开始一个干净会话（清空 memory）
  /clear    清屏
  /quit     退出（同 exit / quit）

多行输入：每行末尾加反斜杠 \\ 续行，回车空行提交。
"""
    )


def _print_config() -> None:
    from config import print_config_summary
    print_config_summary()


def _print_route(agent: Agent) -> None:
    decision = agent.last_route_decision
    if decision is None:
        print("尚无路由决策（先发一条消息）。")
        return
    print(
        f"路由: {decision.route_name} → {decision.model_name}"
        f"\n  reason     : {decision.reason}"
        f"\n  confidence : {decision.confidence:.3f}"
        f"\n  enabled    : {decision.enabled}"
    )


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s - %(message)s",
    )
    # Quiet down noisy INFO logs during interactive use.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)

    validate_config()

    registry = ToolRegistry()
    system_prompt = build_system_prompt(registry.get_tool_specs())
    agent = Agent(system_prompt=system_prompt, tool_registry=registry)

    _setup_readline()
    _print_banner(agent)

    while True:
        try:
            user_input = _read_multiline()
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye!")
            break

        if not user_input:
            continue

        stripped = user_input.strip()
        lower = stripped.lower()

        if lower in {"exit", "quit", "/quit", "/exit"}:
            print("Goodbye!")
            break
        if lower in {"/help", "help", "?"}:
            _print_help()
            continue
        if lower == "/config":
            _print_config()
            continue
        if lower == "/route":
            _print_route(agent)
            continue
        if lower == "/reset":
            agent = Agent(system_prompt=system_prompt, tool_registry=registry)
            print("已重置会话。")
            continue
        if lower in {"/clear", "clear"}:
            os.system("cls" if os.name == "nt" else "clear")
            _print_banner(agent)
            continue

        print("Agent (思考中, 可能需要几十秒) ...", flush=True)
        try:
            response = agent.run(user_input)
        except Exception as e:
            print(f"\nError: {str(e)}")
            continue

        print("\nAgent:")
        print(response)
        print()


if __name__ == "__main__":
    main()
