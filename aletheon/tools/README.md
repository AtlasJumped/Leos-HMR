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

## 2. Check the machine (changes nothing)

```bash
bash claude-readiness-check.sh | tee ~/claude-readiness-report.txt
```

Every WARN and FAIL line comes with a suggested fix. Skim the report before sharing it anywhere: it
lists your hostname, paths, open ports and SSH key labels (no passwords or tokens).

## 3. Add the recommended Claude Code safety rules

```bash
bash apply-claude-settings.sh --dry-run   # look at the change
bash apply-claude-settings.sh             # write it (asks first, keeps a backup)
claude auto-mode critique                 # Claude Code's own feedback on the rules
```

What this adds to `~/.claude/settings.json`, keeping everything already there:

- **Auto-mode context:** what the machine is, and that `/tank`, the iCloud library, `~/.ssh`,
  your Claude login file and Chrome profile hold private data.
- **Auto-mode soft blocks:** destroying or rolling back ZFS pools, datasets or snapshots; wiping,
  formatting or repartitioning disks; deleting under `/tank` or the photo library; copying photos
  off the machine; removing kernel, NVIDIA, ZFS or Plasma packages; release upgrades. Claude stops
  and asks unless you named that exact target.
- **Auto-mode hard block:** sending SSH private keys or your Claude login anywhere off the machine.
- **Always-ask rules:** literal `zfs destroy`, `zpool destroy`, `wipefs`, `mkfs`, `dd`, `parted`
  and similar commands always prompt, in every mode.
- **File-tool read blocks** on your Claude login file and SSH private keys. These are a speed bump,
  not a wall: they don't stop `cat` through Bash.

Every list keeps `"$defaults"`. Without it, Claude Code drops its built-in protections for that list.
If the diff shows two "Primary use:" lines (one from your earlier `/auto-mode-setup` run), delete one.

## 4. Stop starting Claude Code from your home folder

Starting in `/home/leo` makes your whole home folder the working directory. Claude can then read
and edit anything under it, including `~/.claude`, without asking. Trust is also never saved
there, so you're asked again each launch. Your home folder is also an empty git repository, so
"don't ask again" approvals land in your user-wide settings.

```bash
git -C ~ ls-files | wc -l                  # should print 0
mv ~/.git ~/.git.unused-$(date +%F)        # only if it printed 0
mkdir -p ~/sysadmin && cd ~/sysadmin && git init
printf '# System administration workspace\n@~/Documents/TECH_STACK.md\n' > CLAUDE.md
claude                                      # start sessions here from now on
```

Use a project's own folder (for example `~/src/Leos-HMR`) for project work.

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

The session then appears in claude.ai/code and the Claude app while that command keeps running
(run it inside `tmux` so it survives closing the terminal). It needs your claude.ai login, so if
`ANTHROPIC_API_KEY` is set in your shell, Remote Control refuses to start.
