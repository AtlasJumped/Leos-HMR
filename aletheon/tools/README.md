# Workstation setup tools for Claude Code

Run these on the workstation itself, in a desktop terminal, as your normal user.

## 0. Get the files

```bash
gh auth login        # only if gh says you're logged out
git clone -b claude/lucid-darwin-hhyqt8 https://github.com/AtlasJumped/Leos-HMR ~/src/Leos-HMR
cd ~/src/Leos-HMR/aletheon/tools
```

## 1. Finish the update

If `apt` printed "a reboot is required", reboot before going further.

## 2. Check the machine

```bash
bash claude-readiness-check.sh | tee ~/claude-readiness-report.txt
claude doctor
```

The check installs nothing, needs no sudo and writes no files. Its only network use is asking
GitHub whether your `gh` login is valid and which account your SSH key belongs to. Every WARN and
FAIL line comes with a suggested fix. Skim the report before sharing it anywhere: it lists your
hostname, paths, open ports and SSH key labels (no passwords or tokens).

## 3. Add the recommended Claude Code safety rules

```bash
bash apply-claude-settings.sh --dry-run   # look at the change (touches nothing)
bash apply-claude-settings.sh             # write it (asks first, keeps a backup)
claude auto-mode critique                 # Claude Code's own feedback on the rules
```

What this adds to `~/.claude/settings.json`. It keeps everything already there, and keeps the
file's permissions and any dotfiles symlink.

- **Auto-mode context:** describes the machine and names the places holding private data:
  `/tank`, the iCloud library, `~/.ssh`, your Claude login file and Chrome profile. If your
  earlier `/auto-mode-setup` run wrote its own "Primary use of Claude Code", "Host containment" or
  "Sensitive data locations" line, this replaces it so there's one answer per slot.
- **Auto-mode soft blocks:** in auto mode, Claude won't do these unless you named the exact
  target yourself:
  - destroying or rolling back ZFS pools, datasets or snapshots
  - wiping, formatting or repartitioning disks
  - deleting under `/tank` or the photo library, or copying photos off the machine
  - removing kernel, NVIDIA, ZFS or Plasma packages, or a release upgrade
- **Auto-mode hard block:** sending SSH private keys or your Claude login anywhere off the
  machine. You can't approve this one even when you ask for it, so do key moves yourself.
- **Ask rules:** any command containing `zfs destroy`, `zfs rollback`, `zpool destroy`,
  `zpool labelclear`, `wipefs`, `mkfs`, `sgdisk`, `parted`, `fdisk`, `of=/dev/` or
  `do-release-upgrade` stops and asks you. That holds in default, auto and bypass modes. In
  "don't ask" mode these commands are refused instead.
- **Read blocks** on your Claude login file and SSH private keys (`~/.ssh/id_*`, which also
  covers the `.pub` files). They stop Claude's file tools, plus `cat`, `head`, `tail`, `sed`,
  `tee` and redirections on those paths. They don't stop a Python or Node script that opens the
  file itself.

Each auto-mode list keeps `"$defaults"`. Without it, Claude Code drops its built-in protections
for that list.

## 4. Stop starting Claude Code from your home folder

Starting in `/home/leo` makes your whole home folder Claude's working directory. Claude reads
anything under it without asking. Edits still ask in default mode or go through the classifier in
auto mode. Trust is also never saved there, so you're asked again at every launch.

Your home folder is also an empty git repository. That makes every folder under it count as
"inside a repo". It also means an accidental `git add -A` could stage your SSH keys and Claude
login.

```bash
git -C ~ ls-files | wc -l                  # should print 0
mv ~/.git ~/.git.unused-$(date +%F)        # only if it printed 0
mkdir -p ~/sysadmin && cd ~/sysadmin && git init
printf '# System administration workspace for this PC\n' > CLAUDE.md
```

Then load your machine notes in every session by adding this line to `~/.claude/CLAUDE.md`. In
that file the import loads without an approval prompt:

```
@~/Documents/TECH_STACK.md
```

Start sessions with `cd ~/sysadmin && claude` from now on, and use a project's own folder (for
example `~/src/Leos-HMR`) for project work.

## 5. Fix the rest with Claude Code on this PC

Start `claude` in `~/sysadmin` and paste:

> Read ~/claude-readiness-report.txt. Fix each WARN and FAIL one at a time. Before anything that
> needs sudo, deletes data or touches ZFS pools, tell me what you'll run and wait for my OK. Also
> correct the machine name in ~/.claude/CLAUDE.md, and refresh ~/Documents/TECH_STACK.md from
> what you find. In particular: Plasma 6.6 on Wayland, not 5.27/X11; stable PyTorch cu130 works
> on the 5090s, so nightly is no longer required; the current Node version.

## 6. Let claude.ai and your phone drive this PC (optional)

```bash
cd ~/sysadmin && claude remote-control
```

The session then shows up in claude.ai/code and the Claude app for as long as that command keeps
running. Run it inside `tmux` so it survives closing the terminal. It needs your claude.ai login:
if `ANTHROPIC_API_KEY` is set in your shell, Remote Control won't start.
