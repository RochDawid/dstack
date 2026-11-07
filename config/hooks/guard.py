"""dstack guard: a PreToolUse hook that blocks shell commands which destroy work.

Claude Code and Codex both run this before every shell tool call (through
``guard.sh``). Agents run without permission prompts, so this is the only
safety net between a confused agent and a lost afternoon. The hook reads the
tool payload as JSON on stdin::

    {"tool_input": {"command": "<string>" | ["argv", ...], "workdir": "..."},
     "cwd": "..."}

Exit 0 allows the command. Exit 2 blocks it, and the one-line reason on stderr
is shown to the agent. ``DSTACK_GUARD=off`` in the environment that launches
the agent disables the guard (``guard.sh`` checks it before starting Python).

How it decides
==============

The guard does not grep the command text. It parses it the way a shell
would, then judges each simple command on its argv:

1. Lex. A small quote-aware lexer (``lex``) splits the text into words and
   operators. ``shlex`` cannot do this job alone: it returns ``';'`` and
   ``;`` as the same token, and it knows nothing of ``$(...)``, backticks,
   heredocs, or newlines as separators. The lexer records, for each piece of
   a word, whether it was bare, single-quoted or double-quoted, so variable,
   tilde and glob expansion happen only where the shell would do them.
   Quoted text stays one word, so a commit message that says
   "never use git reset --hard" is just an argument to ``git commit``.
2. Split into simple commands on ``;`` ``&&`` ``||`` ``|`` ``|&`` ``&``
   newlines and parentheses. Redirections are dropped. ``( ... )`` subshells
   scope ``cd``.
3. Normalise each command: drop leading ``NAME=value`` assignments, then
   peel wrappers (``sudo``, ``doas``, ``env``, ``command``, ``builtin``,
   ``nice``, ``nohup``, ``time``, ``timeout``, ``stdbuf``, ``ionice``,
   ``exec``, ``xargs``) with their options. Commands are matched on the
   basename, so ``/usr/bin/git`` and ``\\rm`` count.
4. Recurse into code that runs as shell: ``bash|sh|zsh|dash|ksh -c``,
   ``eval``, ``$(...)``, backticks, ``<(...)``/``>(...)``, ``env -S``,
   ``sudo -s|-i``, ``watch``, ``trap``, ``git submodule foreach``, ``find -exec``, a heredoc or
   here-string fed to a shell (``bash <<EOF``, ``bash <<< '...'``), and
   ``echo|printf|cat <<EOF`` piped into a shell. Substitutions inside
   double quotes and unquoted heredoc bodies run, so they are checked too.
   Heredoc bodies fed to anything else (``cat``, ``git commit -F -``,
   ``python``) are data and never trigger a block.
5. Track state within one command line: ``cd``/``pushd``/``popd``,
   ``env -C``, ``sudo -D``, and plain variable assignments
   (``X=/; rm -rf $X``). Anything the guard cannot know (``cd "$DIR"``,
   ``popd``, a ``for`` loop variable, ``$1``) becomes unknown, and an
   unknown value in a deletion target blocks.

Fail closed: unparseable JSON, a missing ``python3``, or an internal error
blocks with a message that names ``DSTACK_GUARD=off``. A command the lexer
cannot parse (unbalanced quotes, a ``$(`` with no ``)``) gets a conservative
regex check instead, and the block message says so. Such a command would not
run in a shell either, so the fallback costs little.

Rules
=====

Every rule names a safer alternative in its block message.

git (global options ``-C``, ``-c``, ``--git-dir``, ``--work-tree``,
``--namespace``, ``--no-pager``, ``-p`` ... are skipped to find the
subcommand; long options also match by unambiguous prefix, as git does):

push-force
    ``push -f``/``--force``, ``f`` inside a short cluster (``-fu``), a
    ``+refspec`` (``+main``, ``+HEAD:main``), or ``--mirror``. Overwrites
    remote history that others may have built on. Allowed:
    ``--force-with-lease`` and ``--force-if-includes``, which refuse to
    clobber work you have not seen.
push-delete
    ``push --delete``/``-d``, a ``:branch`` refspec, or ``--prune``.
    Deletes remote branches. (``git push origin :`` is the "matching"
    refspec, not a deletion, and is allowed.)
reset-hard
    ``reset --hard``. Discards uncommitted changes with no undo. Allowed:
    ``git stash``, then reset; or ``git reset --keep``.
clean-force
    ``clean -f``/``--force`` unless ``-n``/``--dry-run``. Deletes untracked
    files, which git never had a copy of.
discard-worktree
    ``checkout``/``restore`` of the whole tree (``.``, ``./``, ``*``,
    ``:/``, ``:(top)``, or a path that resolves to the repo root or above),
    including ``checkout -- .``, ``checkout HEAD .`` and
    ``restore --staged --worktree .``. ``restore --staged .`` alone only
    unstages, keeps the working tree, and is allowed. Single paths
    (``git checkout -- file.py``) are allowed: reverting one file you just
    edited is routine.
checkout-force
    ``checkout -f``/``--force``, ``switch -f``/``--force``/
    ``--discard-changes``. Throws away local changes while switching.
rm-force-tree
    ``git rm -f`` of the whole tree (``--cached`` is allowed: index only).
branch-force-delete
    ``branch -D``, ``branch -d -f``, ``branch --delete --force``. Deletes
    branches that are not merged anywhere. Allowed: ``git branch -d``.
stash-drop
    ``stash drop``, ``stash clear``. Stashes have no reflog safety net once
    dropped. Allowed: ``git stash list`` / ``git stash show``.
history-rewrite
    ``filter-branch``, ``filter-repo`` (also run as ``git-filter-repo``).
reflog-expire
    ``reflog expire``, ``reflog delete``. Removes the safety net that makes
    most other mistakes recoverable.
gc-prune
    ``gc --prune=now|all``, ``-c gc.pruneExpire=now gc``, and ``git prune``
    (which prunes every unreachable object regardless of age) unless
    ``-n``/``--dry-run``. Unreachable objects are how lost commits come back.
update-ref-delete
    ``update-ref -d``/``--delete``. Deletes a ref with no reflog trail.

rm (any spelling of the flags: ``-rf``, ``-Rf``, ``-fr``, ``-r -f``,
``--recursive --force``, abbreviated long options, flags after the targets):

rm-recursive
    A recursive ``rm`` (with or without ``-f``: without a terminal, ``rm -r``
    does not prompt either) of any target that is not strictly inside an
    allowed root. Allowed roots: the git toplevel of the working directory
    (or the working directory itself outside a repo, but never ``/`` or a
    directory containing ``$HOME``), ``$TMPDIR``, ``/tmp``,
    ``/private/tmp``, ``/var/folders``. Targets expand ``~``, ``$HOME``,
    ``${HOME}``, ``$PWD``, ``$OLDPWD``, ``$TMPDIR``, ``$USER`` and variables
    assigned earlier in the same command, then resolve with ``realpath``
    against the tracked working directory (the last component is not
    followed, since ``rm`` removes a symlink, not its target). Also blocked:
    an allowed root itself (``rm -rf .`` at the project root), ``$HOME`` or
    ``/`` or any ancestor of them, any ``.git`` directory, a match-everything
    glob (``*``, ``.*``, ``*.*``) directly in a root or outside one
    (``rm -rf *``, ``/*``, ``~/*``), and any target containing an expansion
    the guard cannot resolve (fail safe). Non-recursive ``rm`` is not
    policed: it removes single files, and refuses directories.
rm-xargs
    ``... | xargs rm -r``: targets come from stdin. When the producer is
    ``find``, its search paths are checked as for ``find -delete``; any
    other producer blocks, because the targets are unknowable.
find-delete
    ``find PATH ... -delete`` or ``-exec|-execdir|-ok|-okdir rm|unlink|
    rmdir|shred``: every search path (default ``.``) must be inside an
    allowed root. A path that is a root itself is allowed only when the
    expression has a name/path/time/size test (``find . -name '*.pyc'
    -delete``), since ``find . -delete`` or ``find . -type f -delete``
    empties the project. Other ``-exec`` commands are checked as commands.

Non-goals (not blocked; say so rather than pretend): code run by other
interpreters (``python -c 'shutil.rmtree(...)'``), scripts on disk
(``bash ./x.sh``), git aliases (including ``git -c alias.x=...``), a command
name held in a variable (``$RM -rf``), ``curl | sh``, remote commands
(``ssh host '...'``), ``git worktree remove --force`` (agents use worktrees
as scratch space), and other destructive tools (``mv`` over a
directory, ``dd``, ``mkfs``, ``chmod -R``, ``> file``). The guard targets
the mistakes agents actually make with git and rm.
"""

import json
import os
import re
import sys

MAX_DEPTH = 12

SHELLS = {"bash", "sh", "zsh", "dash", "ksh", "mksh", "ash", "fish"}
RM_LIKE = {"rm", "unlink", "rmdir", "shred", "srm"}
TOOL_FAIL = "Set DSTACK_GUARD=off in the agent's environment to bypass the guard."


class ParseError(Exception):
    pass


class Blocked(Exception):
    def __init__(self, rule, command, why, alternative):
        Exception.__init__(self, rule)
        self.rule = rule
        self.command = command
        self.why = why
        self.alternative = alternative

    def message(self):
        cmd = " ".join(self.command.split())
        if len(cmd) > 160:
            cmd = cmd[:157] + "..."
        return (
            "dstack guard blocked [%s] `%s`: %s. Safer: %s. "
            "If it is really intended, ask the user to run it."
            % (self.rule, cmd, self.why, self.alternative)
        )


# --------------------------------------------------------------------------
# Lexer
# --------------------------------------------------------------------------

# Word part modes: "bare" (unquoted: tilde, variables and globs expand),
# "dq" (double-quoted: variables expand), "lit" (single-quoted or escaped),
# "sub" (a command/process substitution; its text is the inner script).
OPERATORS = (
    "<<<", "&>>", ";;&", "<<-",
    "&&", "||", ";;", ";&", "|&", ">>", "<<", ">&", "<&", "&>", "<>", ">|",
    ";", "&", "|", "(", ")", "<", ">",
)
REDIRECTS = {"<<<", "&>>", "<<-", ">>", "<<", ">&", "<&", "&>", "<>", ">|", "<", ">"}
SEPARATORS = {";", "&", "&&", "||", ";;", ";&", ";;&", "\n"}
PIPES = {"|", "|&"}
WORD_BREAK = set(" \t\n;&|()<>")


class Word(object):
    __slots__ = ("parts", "start", "end", "heredoc")

    def __init__(self, parts, start, end):
        self.parts = parts
        self.start = start
        self.end = end
        self.heredoc = None  # (body, expands) when this word is a heredoc delimiter

    @property
    def value(self):
        out = []
        for mode, text in self.parts:
            out.append("$(%s)" % text if mode == "sub" else text)
        return "".join(out)

    @property
    def quoted(self):
        return any(mode != "bare" for mode, _ in self.parts)

    @classmethod
    def literal(cls, text):
        return cls([("lit", text)], 0, 0)


def _scan_quote(s, i):
    """s[i] is a single quote; return the index after the closing quote."""
    j = s.find("'", i + 1)
    if j < 0:
        raise ParseError("unterminated single quote")
    return j + 1


def _scan_backtick(s, i):
    j = i + 1
    while j < len(s):
        if s[j] == "\\":
            j += 2
            continue
        if s[j] == "`":
            return j + 1
        j += 1
    raise ParseError("unterminated backtick")


def _scan_dq(s, i):
    """s[i] is a double quote; return the index after the closing quote."""
    j = i + 1
    n = len(s)
    while j < n:
        c = s[j]
        if c == "\\":
            j += 2
        elif c == '"':
            return j + 1
        elif c == "`":
            j = _scan_backtick(s, j)
        elif s.startswith("$(", j):
            j = _scan_paren(s, j + 2)
        else:
            j += 1
    raise ParseError("unterminated double quote")


def _scan_paren(s, i):
    """Scan from just inside an opening paren; return the index after its match."""
    depth = 1
    j = i
    n = len(s)
    while j < n:
        c = s[j]
        if c == "\\":
            j += 2
            continue
        if c == "'":
            j = _scan_quote(s, j)
            continue
        if c == '"':
            j = _scan_dq(s, j)
            continue
        if c == "`":
            j = _scan_backtick(s, j)
            continue
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                return j + 1
        j += 1
    raise ParseError("unterminated $( or (")


def _scan_brace(s, i):
    """s[i:i+2] == '${'; return the index after the matching brace."""
    depth = 0
    j = i + 1
    n = len(s)
    while j < n:
        c = s[j]
        if c == "\\":
            j += 2
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return j + 1
        elif c == "'":
            j = _scan_quote(s, j)
            continue
        elif c == '"':
            j = _scan_dq(s, j)
            continue
        j += 1
    raise ParseError("unterminated ${")


_ANSI_ESCAPES = {"n": "\n", "t": "\t", "r": "\r", "\\": "\\", "'": "'", '"': '"',
                 "a": "\a", "b": "\b", "e": "\x1b", "E": "\x1b", "f": "\f", "v": "\v"}


def _scan_ansi(s, i):
    """s[i:i+2] == "$'"; return (decoded text, index after the closing quote)."""
    out = []
    j = i + 2
    n = len(s)
    while j < n:
        c = s[j]
        if c == "\\" and j + 1 < n:
            out.append(_ANSI_ESCAPES.get(s[j + 1], "\\" + s[j + 1]))
            j += 2
        elif c == "'":
            return "".join(out), j + 1
        else:
            out.append(c)
            j += 1
    raise ParseError("unterminated $'")


def substitutions(text):
    """Command substitutions in an unquoted-heredoc body (quotes are literal there)."""
    subs = []
    i = 0
    n = len(text)
    while i < n:
        c = text[i]
        if c == "\\":
            i += 2
        elif text.startswith("$((", i):
            i = _scan_paren(text, i + 2)
        elif text.startswith("$(", i):
            j = _scan_paren(text, i + 2)
            subs.append(text[i + 2:j - 1])
            i = j
        elif c == "`":
            j = _scan_backtick(text, i)
            subs.append(text[i + 1:j - 1])
            i = j
        else:
            i += 1
    return subs


def lex(s):
    """Split shell source into Word objects and operator strings."""
    tokens = []
    parts = []
    start = [None]
    pending_heredocs = []
    expect_delim = [None]
    i = 0
    n = len(s)

    def add(mode, text, pos):
        if start[0] is None:
            start[0] = pos
        if mode == "bare" and parts and parts[-1][0] == "bare":
            parts[-1] = ("bare", parts[-1][1] + text)
        else:
            parts.append((mode, text))

    def flush(end):
        if start[0] is None:
            return
        w = Word(list(parts), start[0], end)
        del parts[:]
        start[0] = None
        tokens.append(w)
        if expect_delim[0] is not None:
            pending_heredocs.append((w, expect_delim[0]))
            expect_delim[0] = None

    while i < n:
        c = s[i]
        if c in " \t\r":
            flush(i)
            i += 1
        elif c == "\n":
            flush(i)
            tokens.append("\n")
            i += 1
            while pending_heredocs:
                word, strip_tabs = pending_heredocs.pop(0)
                delim = word.value
                body = []
                while i < n:
                    eol = s.find("\n", i)
                    line = s[i:] if eol < 0 else s[i:eol]
                    i = n if eol < 0 else eol + 1
                    check = line.lstrip("\t") if strip_tabs else line
                    if check == delim:
                        break
                    body.append(line)
                word.heredoc = ("\n".join(body), not word.quoted)
        elif c == "\\":
            if i + 1 < n and s[i + 1] == "\n":
                i += 2  # line continuation
            elif i + 1 < n:
                add("lit", s[i + 1], i)
                i += 2
            else:
                add("lit", "\\", i)
                i += 1
        elif c == "'":
            j = _scan_quote(s, i)
            add("lit", s[i + 1:j - 1], i)
            i = j
        elif c == '"':
            j = _scan_dq(s, i)
            _add_dq(s[i + 1:j - 1], i, add)
            i = j
        elif c == "$" and s.startswith("$'", i):
            text, j = _scan_ansi(s, i)
            add("lit", text, i)
            i = j
        elif s.startswith("$((", i):
            j = _scan_paren(s, i + 2)
            add("bare", s[i:j], i)
            i = j
        elif s.startswith("$(", i) or s.startswith("<(", i) or s.startswith(">(", i):
            j = _scan_paren(s, i + 2)
            add("sub", s[i + 2:j - 1], i)
            i = j
        elif c == "`":
            j = _scan_backtick(s, i)
            add("sub", s[i + 1:j - 1].replace("\\`", "`"), i)
            i = j
        elif s.startswith("${", i):
            j = _scan_brace(s, i)
            add("bare", s[i:j], i)
            i = j
        elif c == "#" and start[0] is None:
            eol = s.find("\n", i)
            i = n if eol < 0 else eol
        elif c in ";&|()<>":
            # A bare all-digit word right before a redirect is a file descriptor.
            if c in "<>" and start[0] is not None and len(parts) == 1 \
                    and parts[0][0] == "bare" and parts[0][1].isdigit():
                del parts[:]
                start[0] = None
            flush(i)
            for op in OPERATORS:
                if s.startswith(op, i):
                    break
            tokens.append(op)
            if op in ("<<", "<<-"):
                expect_delim[0] = op == "<<-"
            i += len(op)
        else:
            add("bare", c, i)
            i += 1
    flush(n)
    return tokens


def _add_dq(inner, offset, add):
    """Split double-quoted text into dq text, escaped literals, and substitutions."""
    buf = []
    i = 0
    n = len(inner)

    def flush():
        if buf:
            add("dq", "".join(buf), offset)
            del buf[:]

    while i < n:
        c = inner[i]
        if c == "\\" and i + 1 < n:
            nxt = inner[i + 1]
            if nxt in '$`"\\':
                flush()
                add("lit", nxt, offset)
            elif nxt != "\n":
                buf.append(inner[i:i + 2])
            i += 2
        elif inner.startswith("$((", i):
            j = _scan_paren(inner, i + 2)
            buf.append(inner[i:j])
            i = j
        elif inner.startswith("$(", i) or c == "`":
            flush()
            if c == "`":
                j = _scan_backtick(inner, i)
                add("sub", inner[i + 1:j - 1], offset)
            else:
                j = _scan_paren(inner, i + 2)
                add("sub", inner[i + 2:j - 1], offset)
            i = j
        else:
            buf.append(c)
            i += 1
    flush()
    if not n:
        add("dq", "", offset)


# --------------------------------------------------------------------------
# Context: working directory, variables, allowed roots
# --------------------------------------------------------------------------

def _real(p):
    p = os.path.realpath(p)
    return "/" + p.lstrip("/") if p.startswith("//") else p


def _inside(path, root):
    """True when path is strictly inside root."""
    return path != root and path.startswith(root.rstrip("/") + "/")


def _within(path, root):
    return path == root or _inside(path, root)


class Roots(object):
    """Allowed deletion roots, computed once per hook run on first use."""

    def __init__(self, start_cwd):
        self.start_cwd = start_cwd
        self._roots = None
        self.home = _real(os.path.expanduser("~"))

    def bad(self, path):
        """Never a valid root: / and any directory that contains $HOME."""
        return path == "/" or _within(self.home, path)

    @property
    def project(self):
        _ = self.roots  # computes _project
        return self._project

    @property
    def roots(self):
        if self._roots is None:
            roots = []
            self._project = None
            cwd = self.start_cwd
            top = _git_toplevel(cwd) if cwd else None
            if top and not self.bad(top):
                self._project = top
            elif cwd and not self.bad(cwd):
                self._project = cwd
            if self._project:
                roots.append(self._project)
            tmp = os.environ.get("TMPDIR")
            for r in ([tmp] if tmp else []) + ["/tmp", "/private/tmp", "/var/folders"]:
                r = _real(r)
                if not self.bad(r) and r not in roots:
                    roots.append(r)
            self._roots = roots
        return self._roots


def _git_toplevel(cwd):
    """Walk up to the nearest directory holding .git (a dir, or a file for worktrees)."""
    d = cwd
    while True:
        if os.path.exists(os.path.join(d, ".git")):
            return d
        parent = os.path.dirname(d)
        if parent == d:
            return None
        d = parent


UNKNOWN = object()
ENV_VARS = ("HOME", "TMPDIR", "USER", "LOGNAME")


class Ctx(object):
    def __init__(self, cwd, roots, depth=0):
        self.cwd = cwd          # None when unknown
        self.oldpwd = None
        self.dirstack = []
        self.vars = {}          # name -> str or UNKNOWN
        self.roots = roots
        self.depth = depth

    def child(self):
        c = Ctx(self.cwd, self.roots, self.depth + 1)
        c.oldpwd = self.oldpwd
        c.vars = dict(self.vars)
        c.dirstack = list(self.dirstack)
        return c

    def var(self, name):
        if name in self.vars:
            v = self.vars[name]
            return None if v is UNKNOWN else v
        if name == "PWD":
            return self.cwd
        if name == "OLDPWD":
            return self.oldpwd
        if name in ENV_VARS:
            return os.environ.get(name) or None
        return None

    def chdir(self, path):
        """Apply cd; path is an expanded string or None for unknown."""
        self.oldpwd = self.cwd
        if path is None:
            self.cwd = None
        elif os.path.isabs(path):
            self.cwd = _real(path)
        elif self.cwd is None:
            self.cwd = None
        else:
            self.cwd = _real(os.path.join(self.cwd, path))


_VAR_RE = re.compile(r"\$(?:\{([A-Za-z_][A-Za-z0-9_]*)\}|([A-Za-z_][A-Za-z0-9_]*))")


def _expand_vars(text, ctx, mask_out, out, glob):
    """Append text to out with $VAR expanded; return False on anything unknown."""
    i = 0
    n = len(text)
    while i < n:
        c = text[i]
        if c == "$" and i + 1 < n:
            m = _VAR_RE.match(text, i)
            if not m:
                return False  # $1, $@, ${X:-y}, $((...)) and friends
            v = ctx.var(m.group(1) or m.group(2))
            if v is None:
                return False
            out.extend(v)
            mask_out.extend([False] * len(v))
            i = m.end()
            continue
        out.append(c)
        mask_out.append(glob and c in "*?[")
        i += 1
    return True


def expand(word, ctx):
    """Expand a word as the shell would for a path: (text, glob_mask) or None."""
    out = []
    mask = []
    for idx, (mode, text) in enumerate(word.parts):
        if mode == "sub":
            return None
        if mode == "lit":
            out.extend(text)
            mask.extend([False] * len(text))
            continue
        if mode == "bare" and idx == 0 and text.startswith("~"):
            m = re.match(r"~([^/]*)", text)
            user = m.group(1)
            if user == "":
                home = ctx.var("HOME")
            elif user == "+":
                home = ctx.cwd
            elif user == "-":
                home = ctx.oldpwd
            elif re.match(r"^[A-Za-z0-9._-]+$", user):
                home = os.path.expanduser("~" + user)
                home = None if home.startswith("~") else home
            else:
                home = None
            if home is None:
                return None
            out.extend(home)
            mask.extend([False] * len(home))
            text = text[m.end():]
        if not _expand_vars(text, ctx, mask, out, glob=(mode == "bare")):
            return None
    return "".join(out), mask


def expand_plain(word, ctx):
    r = expand(word, ctx)
    return None if r is None else r[0]


# --------------------------------------------------------------------------
# Parsing commands out of tokens
# --------------------------------------------------------------------------

class Simple(object):
    """One simple command: its words, redirections, and the command piped into it."""
    __slots__ = ("words", "redirects", "producer", "source")

    def __init__(self, source):
        self.words = []
        self.redirects = []
        self.producer = None
        self.source = source

    def raw(self):
        if not self.words:
            return ""
        if self.words[0].end == 0:  # synthetic argv
            return " ".join(w.value for w in self.words)
        return self.source[self.words[0].start:self.words[-1].end]


KEYWORDS = {"if", "then", "else", "elif", "fi", "do", "done", "while", "until",
            "!", "{", "}", "function", "esac", "in"}


def analyze_script(src, ctx):
    if ctx.depth > MAX_DEPTH:
        raise Blocked("too-deep", src, "command nesting is too deep to check",
                      "run the inner command directly")
    tokens = lex(src)
    stack = []
    cur = Simple(src)
    prev = None  # previous Simple in the current pipeline
    i = 0
    n = len(tokens)

    def finish(pipe):
        # Returns the Simple to use as the next producer.
        if cur.words or cur.redirects:
            check_simple(cur, ctx)
        return cur if pipe else None

    while i < n:
        t = tokens[i]
        if isinstance(t, Word):
            cur.words.append(t)
        elif t in REDIRECTS:
            target = tokens[i + 1] if i + 1 < n and isinstance(tokens[i + 1], Word) else None
            cur.redirects.append((t, target))
            if target is not None:
                i += 1
        elif t in PIPES or t in SEPARATORS or t in ("(", ")"):
            prev = finish(t in PIPES)
            cur = Simple(src)
            cur.producer = prev
            if t == "(":
                stack.append(ctx)
                ctx = ctx.child()
                ctx.depth -= 1
            elif t == ")" and stack:
                ctx = stack.pop()
        i += 1
    finish(False)


def check_simple(cmd, ctx):
    # Substitutions run first, in a subshell.
    for w in cmd.words + [r[1] for r in cmd.redirects if r[1] is not None]:
        for mode, text in w.parts:
            if mode == "sub":
                analyze_script(text, ctx.child())
        if w.heredoc and w.heredoc[1]:
            for sub in substitutions(w.heredoc[0]):
                analyze_script(sub, ctx.child())
    words = list(cmd.words)
    # Leading assignments. A command made only of assignments sets variables.
    assigns = []
    while words and _assignment(words[0]):
        assigns.append(words.pop(0))
    if not words:
        for w in assigns:
            _assign(w, ctx)
        return
    check_argv(words, cmd, ctx)


_ASSIGN_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\[[^\]]*\])?\+?=")


def _assignment(word):
    return bool(word.parts) and word.parts[0][0] == "bare" and bool(_ASSIGN_RE.match(word.parts[0][1]))


def _assign(word, ctx):
    first = word.parts[0][1]
    name, _, rest = first.partition("=")
    if name.endswith("+") or "[" in name:
        ctx.vars[name.rstrip("+").split("[")[0]] = UNKNOWN
        return
    value = Word([("bare", rest)] + word.parts[1:], 0, 0)
    v = expand_plain(value, ctx)
    ctx.vars[name] = UNKNOWN if v is None else v


def _base(word):
    return word.value.rsplit("/", 1)[-1]


def check_argv(words, cmd, ctx, xargs=False):
    """Judge one argv (assignments already removed)."""
    ctx_cmd = ctx  # per-command overrides (env -C, sudo -D) use a copy
    while words:
        if _assignment(words[0]):
            words = words[1:]
            continue
        name = _base(words[0])
        if name in KEYWORDS:
            words = words[1:]
            continue
        if name in WRAPPERS:
            words, ctx_cmd, xargs, shell_text = WRAPPERS[name](words[1:], ctx_cmd, xargs)
            if shell_text is not None:
                analyze_script(shell_text, ctx_cmd.child())
                return
            continue
        break
    if not words:
        return
    if words[0].end:
        cmd.words = list(words)  # report and pipe from the real command, not `sudo {`
    name = _base(words[0])
    args = words[1:]
    handler = COMMANDS.get(name)
    if name in SHELLS:
        handler = check_shell
    if handler is not None:
        handler(name, args, cmd, ctx_cmd, xargs)


# ---- wrappers: each returns (remaining words, ctx, xargs, shell_text) ----

def _opts(words, with_arg, long_with_arg=()):
    """Index of the first operand after leading options.

    with_arg lists the short letters that take a value (attached or next word);
    long_with_arg lists long options whose value is the next word.
    """
    i = 0
    while i < len(words):
        a = words[i].value
        if a == "--":
            return i + 1
        if a.startswith("--") and len(a) > 2:
            i += 2 if a[2:] in long_with_arg else 1
            continue
        if a.startswith("-") and len(a) > 1:
            for k, ch in enumerate(a[1:]):
                if ch in with_arg:
                    if k == len(a) - 2:
                        i += 1  # value is the next word
                    break
            i += 1
            continue
        return i
    return i


def w_simple(with_arg="", long_with_arg=()):
    def wrap(words, ctx, xargs):
        return words[_opts(words, with_arg, long_with_arg=long_with_arg):], ctx, xargs, None
    return wrap


def w_sudo(words, ctx, xargs):
    i = 0
    shell = False
    while i < len(words):
        a = words[i].value
        if a == "--":
            i += 1
            break
        if a.startswith("--"):
            if a in ("--login", "--shell"):
                shell = True
            elif a.startswith("--chdir="):
                ctx = ctx.child()
                ctx.depth -= 1
                ctx.chdir(expand_plain(Word.literal(a[8:]), ctx))
            elif a in ("--user", "--group", "--host", "--prompt", "--close-from",
                       "--role", "--type", "--other-user", "--chdir", "--command-timeout"):
                if a == "--chdir" and i + 1 < len(words):
                    ctx = ctx.child()
                    ctx.depth -= 1
                    ctx.chdir(expand_plain(words[i + 1], ctx))
                i += 1
            i += 1
            continue
        if a.startswith("-") and len(a) > 1:
            j = 1
            while j < len(a):
                ch = a[j]
                if ch in "sil":
                    shell = shell or ch in "si"
                if ch in "ugphCrtTUD":
                    val = a[j + 1:]
                    if not val and i + 1 < len(words):
                        i += 1
                        val_word = words[i]
                    else:
                        val_word = Word.literal(val)
                    if ch == "D":
                        ctx = ctx.child()
                        ctx.depth -= 1
                        ctx.chdir(expand_plain(val_word, ctx))
                    break
                j += 1
            i += 1
            continue
        break
    rest = words[i:]
    if shell and rest:
        return [], ctx, xargs, " ".join(w.value for w in rest)
    return rest, ctx, xargs, None


def w_env(words, ctx, xargs):
    i = 0
    while i < len(words):
        a = words[i].value
        if a == "--":
            i += 1
            break
        if a in ("-C", "--chdir") or a.startswith("--chdir=") or (a.startswith("-C") and len(a) > 2):
            if a in ("-C", "--chdir"):
                i += 1
                target = words[i] if i < len(words) else Word.literal("")
            else:
                target = Word.literal(a.split("=", 1)[1] if a.startswith("--") else a[2:])
            ctx = ctx.child()
            ctx.depth -= 1
            ctx.chdir(expand_plain(target, ctx))
            i += 1
            continue
        if a in ("-S", "--split-string") or a.startswith("--split-string=") or (a.startswith("-S") and len(a) > 2):
            if a in ("-S", "--split-string"):
                i += 1
                text = words[i].value if i < len(words) else ""
            else:
                text = a.split("=", 1)[1] if a.startswith("--") else a[2:]
            rest = " ".join(w.value for w in words[i + 1:])
            return [], ctx, xargs, text + " " + rest
        if a in ("-u", "--unset"):
            i += 2
            continue
        if a.startswith("-") and len(a) > 1:
            i += 1
            continue
        if _assignment(words[i]):
            i += 1
            continue
        break
    return words[i:], ctx, xargs, None


def w_xargs(words, ctx, xargs):
    i = _opts(words, "IiEedLlnPsa", long_with_arg=(
        "replace", "eof", "delimiter", "max-lines", "max-args", "max-procs",
        "max-chars", "arg-file", "process-slot-var"))
    return words[i:], ctx, True, None


def w_timeout(words, ctx, xargs):
    i = _opts(words, "sk", long_with_arg=("signal", "kill-after"))
    return words[i + 1:], ctx, xargs, None  # skip DURATION


def w_shell_text(with_arg="", long_with_arg=()):
    """Wrappers that join their operands into a string and run it with sh -c (watch)."""
    def wrap(words, ctx, xargs):
        rest = words[_opts(words, with_arg, long_with_arg=long_with_arg):]
        return [], ctx, xargs, " ".join(w.value for w in rest)
    return wrap


def w_command(words, ctx, xargs):
    i = 0
    while i < len(words) and words[i].value.startswith("-") and words[i].value != "--":
        if "v" in words[i].value or "V" in words[i].value:
            return [], ctx, xargs, None  # lookup only
        i += 1
    if i < len(words) and words[i].value == "--":
        i += 1
    return words[i:], ctx, xargs, None


WRAPPERS = {
    "sudo": w_sudo,
    "doas": w_simple("uC"),
    "env": w_env,
    "command": w_command,
    "builtin": w_simple(),
    "exec": w_simple("a"),
    "nice": w_simple("n", long_with_arg=("adjustment",)),
    "nohup": w_simple(),
    "time": w_simple("fo", long_with_arg=("format", "output")),
    "timeout": w_timeout,
    "stdbuf": w_simple("ioe", long_with_arg=("input", "output", "error")),
    "ionice": w_simple("cnp", long_with_arg=("class", "classdata", "pid")),
    "chronic": w_simple(),
    "unbuffer": w_simple(),
    "xargs": w_xargs,
    "watch": w_shell_text("nq", long_with_arg=("interval", "equexit")),
}


# ---- shells and eval ----

def check_shell(name, args, cmd, ctx, xargs):
    i = 0
    script_flag = False
    while i < len(args):
        a = args[i].value
        if a == "--" or a == "-":
            i += 1
            break
        if a.startswith("--"):
            i += 2 if a in ("--rcfile", "--init-file") else 1
            continue
        if (a.startswith("-") or a.startswith("+")) and len(a) > 1:
            if "c" in a[1:]:
                script_flag = True
            if "o" in a[1:] or "O" in a[1:]:
                i += 1  # -o option takes a value
            i += 1
            continue
        break
    operands = args[i:]
    if script_flag:
        if operands:
            analyze_script(operands[0].value, ctx.child())
        return
    if operands:
        return  # a script file on disk: not inspectable
    # Reads its script from stdin: a heredoc, a here-string, or a pipe.
    for op, target in cmd.redirects:
        if target is None:
            continue
        if op in ("<<", "<<-") and target.heredoc is not None:
            analyze_script(target.heredoc[0], ctx.child())
        elif op == "<<<":
            analyze_script(target.value, ctx.child())
    if cmd.producer is not None:
        text = _produced_text(cmd.producer)
        if text is not None:
            analyze_script(text, ctx.child())


def _produced_text(producer):
    words = [w for w in producer.words if not _assignment(w)]
    if not words:
        return None
    name = _base(words[0])
    if name in ("echo", "printf"):
        args = [w.value for w in words[1:]]
        while args and name == "echo" and re.match(r"^-[neE]+$", args[0]):
            args = args[1:]
        return "\n".join(a.replace("\\n", "\n") for a in args) if name == "printf" else " ".join(args)
    if name == "cat":
        for op, target in producer.redirects:
            if op in ("<<", "<<-") and target is not None and target.heredoc is not None:
                return target.heredoc[0]
            if op == "<<<" and target is not None:
                return target.value
    return None


def check_eval(name, args, cmd, ctx, xargs):
    if args:
        analyze_script(" ".join(w.value for w in args), ctx.child())


def check_trap(name, args, cmd, ctx, xargs):
    vals = [w.value for w in args]
    if vals and vals[0] not in ("-", "-p", "-l", "--"):
        analyze_script(vals[0], ctx.child())


def check_cd(name, args, cmd, ctx, xargs):
    vals = [w for w in args if not (w.value.startswith("-") and len(w.value) > 1)]
    if name == "popd":
        ctx.chdir(ctx.dirstack.pop() if ctx.dirstack else None)
        return
    if name == "pushd":
        if not vals:
            ctx.chdir(None)
            return
        ctx.dirstack.append(ctx.cwd)
    if not vals:
        ctx.chdir(ctx.var("HOME"))
    elif vals[0].value == "-" and not vals[0].quoted:
        ctx.chdir(ctx.oldpwd)
    else:
        ctx.chdir(expand_plain(vals[0], ctx))


def check_unset_like(name, args, cmd, ctx, xargs):
    """read, unset, for, select, local/export/declare: track variable state."""
    if name == "for" or name == "select":
        if args:
            ctx.vars[args[0].value] = UNKNOWN
        return
    for w in args:
        if _assignment(w):
            _assign(w, ctx)
        elif not w.value.startswith("-"):
            ctx.vars[w.value] = UNKNOWN


# --------------------------------------------------------------------------
# Deletion targets
# --------------------------------------------------------------------------

MATCH_ALL = re.compile(r"^(\*|\.\*|\*\.\*|\*\*|\.\?\*|\?\*|\.\[!.\]\*|\[!.\]\*)$")


def target_problem(word, ctx, root_ok=False):
    """Why deleting this target is unsafe, or None. root_ok allows a root itself."""
    roots = ctx.roots
    if not isinstance(word, tuple):
        exp = expand(word, ctx)
        if exp is None:
            return "target %r has an expansion the guard cannot resolve" % word.value
    else:
        exp = word
    path, mask = exp
    if path == "":
        return None
    # Strip trailing slashes (keep one for "/").
    follow = path.endswith("/")
    while len(path) > 1 and path.endswith("/"):
        path = path[:-1]
        mask = mask[:-1]
    if not os.path.isabs(path) and ctx.cwd is None:
        return "target %r is relative to a directory the guard cannot determine" % path
    base_dir = ctx.cwd or "/"
    if any(mask):
        # Find the first component with an unquoted glob character.
        comps = []
        pos = 0
        for comp in path.split("/"):
            comps.append((comp, any(mask[pos:pos + len(comp)])))
            pos += len(comp) + 1
        k = next(idx for idx, (_, g) in enumerate(comps) if g)
        prefix = "/".join(c for c, _ in comps[:k])
        if path.startswith("/") and prefix == "":
            prefix = "/"
        base = _real(os.path.join(base_dir, prefix) if prefix else base_dir)
        globbed = comps[k][0]
        final = k == len(comps) - 1
        if _protected(base, ctx.roots):
            return "glob %r expands inside %s" % (path, base)
        if any(base == r for r in roots.roots):
            if final and MATCH_ALL.match(globbed):
                return "glob %r would empty the root %s" % (path, base)
            return None
        if any(_inside(base, r) for r in roots.roots):
            return None
        return "glob %r is outside the project and temp dirs" % path
    full = os.path.join(base_dir, path)
    head, tail = os.path.split(full)
    if follow or tail in ("", ".", ".."):
        resolved = _real(full)
    else:
        resolved = os.path.join(_real(head), tail)
    if os.path.basename(resolved) == ".git":
        return "%s is a git directory (all history)" % resolved
    if _protected(resolved, roots):
        return "%s is / or contains $HOME" % resolved
    for r in roots.roots:
        if resolved == r:
            if root_ok:
                return None
            return "%s is the %s itself" % (resolved, "project root" if r == roots.project else "temp root")
        if _within(r, resolved):
            return "%s contains the allowed root %s" % (resolved, r)
    if any(_inside(resolved, r) for r in roots.roots):
        return None
    return "%s is outside the project and temp dirs" % resolved


def _protected(path, roots):
    return path == "/" or _within(roots.home, path)


def check_rm(name, args, cmd, ctx, xargs):
    recursive = False
    targets = []
    opts_done = False
    for w in args:
        a = w.value
        if opts_done or not a.startswith("-") or a == "-":
            targets.append(w)
        elif a == "--":
            opts_done = True
        elif a.startswith("--"):
            opt = a[2:].split("=", 1)[0]
            if opt and "recursive".startswith(opt):
                recursive = True
        elif "r" in a or "R" in a:
            recursive = True
    if not recursive:
        return
    for w in targets:
        problem = target_problem(w, ctx)
        if problem:
            raise Blocked("rm-recursive", cmd.raw(), problem,
                          "delete paths inside the project or a temp dir, by explicit path")
    if xargs:
        _check_xargs_producer(cmd, ctx, "rm-xargs")


def _check_xargs_producer(cmd, ctx, rule):
    prod = cmd.producer
    words = [w for w in (prod.words if prod else []) if not _assignment(w)]
    if words and _base(words[0]) == "find":
        paths, filtered = _find_paths(words[1:])
        for p in paths:
            problem = target_problem(p, ctx, root_ok=filtered)
            if problem:
                raise Blocked(rule, cmd.raw(), "find feeds xargs rm: " + problem,
                              "narrow the find path to a directory inside the project")
        return
    raise Blocked(rule, cmd.raw(), "rm -r takes its targets from stdin, which the guard cannot see",
                  "pass explicit paths to rm, or use find PATH ... -delete")


FIND_TESTS = {"-name", "-iname", "-path", "-ipath", "-wholename", "-iwholename", "-regex",
              "-iregex", "-newer", "-mtime", "-mmin", "-ctime", "-cmin", "-atime", "-amin",
              "-size", "-empty", "-user", "-group", "-perm", "-links", "-inum", "-samefile",
              "-lname", "-ilname", "-newermt", "-newerct", "-newerat", "-uid", "-gid"}


def _find_paths(args):
    i = 0
    while i < len(args) and args[i].value in ("-H", "-L", "-P", "-E", "-X", "-s", "-x", "-d") \
            or (i < len(args) and args[i].value.startswith("-O")):
        i += 1
    paths = []
    while i < len(args) and args[i].value in ("-D", "-f"):
        if args[i].value == "-f" and i + 1 < len(args):
            paths.append(args[i + 1])
        i += 2
    while i < len(args):
        a = args[i].value
        if (a.startswith("-") and len(a) > 1) or a in ("(", "!", ")", "\\(", ","):
            break
        paths.append(args[i])
        i += 1
    filtered = any(w.value in FIND_TESTS for w in args[i:])
    return (paths or [Word.literal(".")]), filtered


def check_find(name, args, cmd, ctx, xargs):
    paths, filtered = _find_paths(args)
    deleting = False
    vals = [w.value for w in args]
    i = 0
    while i < len(vals):
        a = vals[i]
        if a == "-delete":
            deleting = True
        elif a in ("-exec", "-execdir", "-ok", "-okdir"):
            j = i + 1
            while j < len(vals) and vals[j] not in (";", "+"):
                j += 1
            argv = args[i + 1:j]
            if argv and _base(argv[0]) in RM_LIKE:
                deleting = True
            elif argv:
                sub = Simple(cmd.source)
                sub.words = list(argv)
                check_argv(list(argv), sub, ctx.child())
            i = j
        i += 1
    if not deleting:
        return
    for p in paths:
        problem = target_problem(p, ctx, root_ok=filtered)
        if problem:
            raise Blocked("find-delete", cmd.raw(), problem,
                          "point find at a directory inside the project and add a -name/-path test")


# --------------------------------------------------------------------------
# git
# --------------------------------------------------------------------------

GIT_GLOBAL_WITH_ARG = {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--super-prefix",
                       "--config-env", "--exec-path", "--attr-source", "--list-cmds"}
WHOLE_TREE = re.compile(r"^(\.|\./|\*|:/|:/\.|:/\*|:\(top\)|:\(top\)\.|:\(top\)\*|:\(top,[^)]*\).*)$")


def _long(a, *names):
    """a is '--x[=v]'; true if x is one of names or an abbreviation (>= 2 chars) of one."""
    if not a.startswith("--"):
        return False
    opt = a[2:].split("=", 1)[0]
    return any(opt == n or (len(opt) >= 2 and n.startswith(opt)) for n in names)


def _short(a, letters, with_arg=""):
    """Letters present in a short-option cluster, stopping at a letter that takes a value."""
    if not a.startswith("-") or a.startswith("--") or len(a) < 2:
        return set()
    found = set()
    for ch in a[1:]:
        found.add(ch)
        if ch in with_arg:
            break
    return found & set(letters)


def _split_opts(args, short_with_arg="", long_with_arg=()):
    """Split git subcommand args into (options, positionals); honours '--'."""
    opts, pos = [], []
    i = 0
    after = False
    while i < len(args):
        a = args[i].value
        if after:
            pos.append(args[i])
        elif a == "--":
            after = True
        elif a.startswith("--") and len(a) > 2:
            opts.append(a)
            if "=" not in a and a[2:] in long_with_arg:
                i += 1
        elif a.startswith("-") and len(a) > 1:
            opts.append(a)
            for k, ch in enumerate(a[1:]):
                if ch in short_with_arg:
                    if k == len(a) - 2:
                        i += 1
                    break
        else:
            pos.append(args[i])
        i += 1
    return opts, pos


def _whole_tree(words, ctx):
    roots = ctx.roots
    for w in words:
        v = w.value
        if WHOLE_TREE.match(v):
            return v
        if ctx.cwd and roots.project and not v.startswith(":"):
            p = expand_plain(w, ctx)
            if p is None:
                continue
            resolved = _real(os.path.join(ctx.cwd, p))
            if _within(roots.project, resolved):
                return v
    return None


def check_git(name, args, cmd, ctx, xargs):
    i = 0
    config = []
    while i < len(args):
        a = args[i].value
        if a in GIT_GLOBAL_WITH_ARG:
            if a == "-c" and i + 1 < len(args):
                config.append(args[i + 1].value.lower())
            i += 2
        elif a.startswith("-"):
            if a.startswith("-c") and len(a) > 2:
                config.append(a[2:].lower())
            i += 1
        else:
            break
    if i >= len(args):
        return
    sub = args[i].value
    rest = args[i + 1:]
    handler = GIT_RULES.get(sub)
    if handler:
        handler(rest, cmd, ctx, config)


def _block(rule, cmd, why, alt):
    raise Blocked(rule, cmd.raw(), why, alt)


def git_push(args, cmd, ctx, config):
    opts, pos = _split_opts(args, "o", ("repo", "receive-pack", "exec", "push-option"))
    for a in opts:
        if _long(a, "force") or "f" in _short(a, "f", "o"):
            _block("push-force", cmd, "force push overwrites remote history",
                   "git push --force-with-lease")
        if _long(a, "mirror"):
            _block("push-force", cmd, "--mirror force-updates and deletes every remote ref",
                   "push the branches you mean, with --force-with-lease if needed")
        if _long(a, "delete") or "d" in _short(a, "d", "o"):
            _block("push-delete", cmd, "deletes a remote branch",
                   "ask the user to delete remote branches")
        if _long(a, "prune"):
            _block("push-delete", cmd, "--prune deletes remote branches with no local counterpart",
                   "push named branches without --prune")
    for w in pos:
        v = w.value
        if v.startswith("+"):
            _block("push-force", cmd, "refspec %r forces the update" % v,
                   "git push --force-with-lease without the leading +")
        if v.startswith(":") and len(v) > 1:
            _block("push-delete", cmd, "refspec %r deletes the remote branch" % v,
                   "ask the user to delete remote branches")


def git_reset(args, cmd, ctx, config):
    opts, _ = _split_opts(args)
    if any(_long(a, "hard") for a in opts):
        _block("reset-hard", cmd, "git reset --hard discards uncommitted changes",
               "git stash (then reset), or git reset --keep")


def git_clean(args, cmd, ctx, config):
    opts, _ = _split_opts(args, "e", ("exclude",))
    force = any(_long(a, "force") or _short(a, "f", "e") for a in opts)
    dry = any(_long(a, "dry-run") or _short(a, "n", "e") for a in opts)
    if force and not dry:
        _block("clean-force", cmd, "git clean -f deletes untracked files git has no copy of",
               "git clean -n to preview, then delete specific paths")


def git_checkout(args, cmd, ctx, config):
    opts, pos = _split_opts(args, "bB", ("orphan", "conflict", "pathspec-from-file"))
    if any(_long(a, "force") or _short(a, "f", "bB") for a in opts):
        _block("checkout-force", cmd, "checkout --force throws away local changes",
               "git stash, then checkout")
    spec = _whole_tree(pos, ctx)
    if spec is not None:
        _block("discard-worktree", cmd, "checkout %s discards every uncommitted change" % spec,
               "git stash, or checkout specific files")


def git_switch(args, cmd, ctx, config):
    opts, _ = _split_opts(args, "cC", ("create", "force-create", "orphan", "conflict"))
    if any(_long(a, "force", "discard-changes") or _short(a, "f", "cC") for a in opts):
        _block("checkout-force", cmd, "switch --discard-changes throws away local changes",
               "git stash, then switch")


def git_restore(args, cmd, ctx, config):
    opts, pos = _split_opts(args, "s", ("source", "pathspec-from-file"))
    staged = any(_long(a, "staged") or _short(a, "S", "s") for a in opts)
    worktree = any(_long(a, "worktree") or _short(a, "W", "s") for a in opts)
    if staged and not worktree:
        return  # only unstages; the working tree is kept
    spec = _whole_tree(pos, ctx)
    if spec is not None:
        _block("discard-worktree", cmd, "restore %s discards every uncommitted change" % spec,
               "git stash, or restore specific files")


def git_rm(args, cmd, ctx, config):
    opts, pos = _split_opts(args, "", ("pathspec-from-file",))
    if any(_long(a, "cached") for a in opts):
        return
    force = any(_long(a, "force") or _short(a, "f") for a in opts)
    dry = any(_long(a, "dry-run") or _short(a, "n") for a in opts)
    spec = _whole_tree(pos, ctx)
    if force and not dry and spec is not None:
        _block("rm-force-tree", cmd, "git rm -f %s deletes every file including uncommitted changes" % spec,
               "git rm --cached, or remove specific paths")


def git_branch(args, cmd, ctx, config):
    opts, _ = _split_opts(args, "u", ("set-upstream-to", "contains", "no-contains", "merged",
                                      "no-merged", "points-at", "format", "sort"))
    letters = set()
    for a in opts:
        letters |= _short(a, "dDf", "u")
    delete = "d" in letters or any(_long(a, "delete") for a in opts)
    force = "f" in letters or any(_long(a, "force") for a in opts)
    if "D" in letters or (delete and force):
        _block("branch-force-delete", cmd, "deletes a branch even if it is not merged",
               "git branch -d (refuses unmerged branches)")


def git_stash(args, cmd, ctx, config):
    pos = [w.value for w in args if not w.value.startswith("-")]
    if pos and pos[0] in ("drop", "clear"):
        _block("stash-drop", cmd, "git stash %s permanently drops stashed work" % pos[0],
               "git stash list / git stash show; leave stashes in place")


def git_history(args, cmd, ctx, config):
    _block("history-rewrite", cmd, "rewrites the whole repository history",
           "git rebase -i on a branch, or ask the user")


def git_reflog(args, cmd, ctx, config):
    pos = [w.value for w in args if not w.value.startswith("-")]
    if pos and pos[0] in ("expire", "delete"):
        _block("reflog-expire", cmd, "removes the reflog, the safety net for lost commits",
               "leave the reflog alone; git gc prunes it on schedule")


def git_gc(args, cmd, ctx, config):
    now = ("now", "all")
    prune = any(_long(a, "prune") and a.partition("=")[2].lower() in now for a in [w.value for w in args])
    prune = prune or any(c.startswith("gc.pruneexpire=") and c.split("=", 1)[1] in now for c in config)
    if prune:
        _block("gc-prune", cmd, "pruning now deletes unreachable commits immediately",
               "git gc (default two-week grace period)")


def git_prune(args, cmd, ctx, config):
    opts, _ = _split_opts(args, "", ("expire",))
    if not any(_long(a, "dry-run") or _short(a, "n") for a in opts):
        _block("gc-prune", cmd, "git prune deletes every unreachable object regardless of age",
               "git gc (default two-week grace period), or git prune -n")


def git_update_ref(args, cmd, ctx, config):
    opts, _ = _split_opts(args, "m")
    if any(a == "-d" or _long(a, "delete") or _short(a, "d", "m") for a in opts):
        _block("update-ref-delete", cmd, "deletes a ref with no reflog trail",
               "git branch -d / git tag -d")


def git_submodule(args, cmd, ctx, config):
    vals = [w.value for w in args]
    if "foreach" in vals:
        rest = [v for v in vals[vals.index("foreach") + 1:] if v not in ("--recursive", "-q", "--quiet")]
        if rest:
            analyze_script(" ".join(rest), ctx.child())


GIT_RULES = {
    "push": git_push,
    "reset": git_reset,
    "clean": git_clean,
    "checkout": git_checkout,
    "switch": git_switch,
    "restore": git_restore,
    "rm": git_rm,
    "branch": git_branch,
    "stash": git_stash,
    "filter-branch": git_history,
    "filter-repo": git_history,
    "reflog": git_reflog,
    "gc": git_gc,
    "prune": git_prune,
    "update-ref": git_update_ref,
    "submodule": git_submodule,
}

COMMANDS = {
    "git": check_git,
    "git-filter-repo": lambda name, args, cmd, ctx, xargs: git_history(args, cmd, ctx, []),
    "rm": check_rm,
    "find": check_find,
    "eval": check_eval,
    "trap": check_trap,
    "cd": check_cd,
    "pushd": check_cd,
    "popd": check_cd,
    "for": check_unset_like,
    "select": check_unset_like,
    "read": check_unset_like,
    "unset": check_unset_like,
    "export": check_unset_like,
    "declare": check_unset_like,
    "typeset": check_unset_like,
    "local": check_unset_like,
    "readonly": check_unset_like,
}


# --------------------------------------------------------------------------
# Fallback for text the lexer cannot parse
# --------------------------------------------------------------------------

FALLBACK = [
    ("push-force", re.compile(r"\bgit\b.*\bpush\b.*(\s-[a-zA-Z]*f|--force(?!-with-lease|-if-includes)|--mirror|\s\+)")),
    ("push-delete", re.compile(r"\bgit\b.*\bpush\b.*(\s-[a-zA-Z]*d\b|--delete|--prune|\s:\S)")),
    ("reset-hard", re.compile(r"\breset\b.*--hard")),
    ("clean-force", re.compile(r"\bclean\b.*(\s-[a-zA-Z]*f|--force)")),
    ("discard-worktree", re.compile(r"\b(checkout|restore)\b.*\s(\.|:/)(\s|$|[;&|])")),
    ("branch-force-delete", re.compile(r"\bbranch\b.*(-D\b|--delete)")),
    ("stash-drop", re.compile(r"\bstash\s+(drop|clear)\b")),
    ("history-rewrite", re.compile(r"filter-(branch|repo)")),
    ("reflog-expire", re.compile(r"\breflog\s+(expire|delete)")),
    ("gc-prune", re.compile(r"--prune=(now|all)|\bgit\s+prune\b")),
    ("update-ref-delete", re.compile(r"\bupdate-ref\b.*(-d\b|--delete)")),
    ("rm-recursive", re.compile(r"\brm\b.*(\s-[a-zA-Z]*[rR]|--rec)")),
    ("find-delete", re.compile(r"\bfind\b.*(-delete|-exec(dir)?\s+\S*rm\b)")),
]


def fallback(command, error):
    for rule, pattern in FALLBACK:
        if pattern.search(command):
            raise Blocked(rule, command,
                          "the command could not be parsed (%s), and a conservative text check "
                          "matched this rule" % error,
                          "fix the quoting so the guard can parse the command")


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------

def check_payload(payload, env_cwd):
    tool_input = payload.get("tool_input") if isinstance(payload, dict) else None
    if not isinstance(tool_input, dict):
        return
    command = tool_input.get("command")
    cwd = payload.get("cwd") if isinstance(payload.get("cwd"), str) and payload.get("cwd") else env_cwd
    cwd = _real(cwd)
    # Codex runs the command in tool_input.workdir; the allowed roots still come from the
    # session's cwd, so a workdir outside the project does not make that directory a root.
    workdir = tool_input.get("workdir")
    shell_cwd = _real(os.path.join(cwd, workdir)) if isinstance(workdir, str) and workdir else cwd
    ctx = Ctx(shell_cwd, Roots(cwd))
    if isinstance(command, list):
        if not command:
            return
        if not all(isinstance(a, str) for a in command):
            raise Blocked("bad-payload", repr(command), "command array has non-string items",
                          "send a list of strings")
        words = [Word.literal(a) for a in command]
        cmd = Simple("")
        cmd.words = words
        check_argv(words, cmd, ctx)
        return
    if not isinstance(command, str) or not command.strip():
        return
    try:
        analyze_script(command, ctx)
    except ParseError as e:
        fallback(command, str(e))


def main():
    raw = sys.stdin.read()
    try:
        payload = json.loads(raw)
    except ValueError:
        sys.stderr.write("dstack guard: could not parse the hook payload as JSON; blocking to stay "
                         "safe. %s\n" % TOOL_FAIL)
        return 2
    try:
        check_payload(payload, os.getcwd())
    except Blocked as b:
        sys.stderr.write(b.message() + "\n")
        return 2
    except Exception as e:  # fail closed on any bug
        sys.stderr.write("dstack guard: internal error (%s: %s); blocking to stay safe. %s\n"
                         % (type(e).__name__, e, TOOL_FAIL))
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
