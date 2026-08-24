# tools

Three scripts. Only the first one is likely to matter to you.

## `install-runner.sh` — CI on your own machine

CI here runs on a self-hosted runner and nowhere else: `helper-tests.yml` is
`runs-on: self-hosted` in every job, with no GitHub-hosted fallback. Until a
runner is registered, jobs queue forever.

Run this **on the machine that should execute CI**:

```sh
tools/install-runner.sh <registration-token>
tools/install-runner.sh --gh          # or mint the token with the gh CLI
```

Get a token from
[Settings → Actions → Runners → New self-hosted runner](https://github.com/mrjamesmyers/omarchy-gremlins/settings/actions/runners/new).
They expire an hour after they are issued.

It installs the runner's dependencies under their Arch names (the runner's own
`installdependencies.sh` only knows Debian, RHEL and SUSE, so on Arch it bails),
resolves the latest release, **verifies the download against the SHA-256 the
release notes publish**, registers the runner, and installs it as a systemd
service so it survives a reboot. It waits for the runner's own
"Listening for Jobs" before declaring success, rather than trusting that the
unit went active.

Re-running it is safe: an existing runner directory is reused and re-registered
with `--replace`.

Overridable with `RUNNER_DIR`, `RUNNER_NAME`, `RUNNER_LABELS`, `RUNNER_VERSION`.

### Worth knowing

A self-hosted runner executes whatever a workflow says, on your hardware. On a
public repository that matters: `helper-tests.yml` already skips pull requests
from forks for exactly this reason, and
[Settings → Actions](https://github.com/mrjamesmyers/omarchy-gremlins/settings/actions)
can additionally require approval before an outside contributor's workflow runs.

### If jobs still queue

```sh
systemctl status 'actions.runner.*'
tail -n 40 ~/actions-runner/_diag/Runner_*.log
```

The runner should also show as **Idle** (not Offline) under
[Settings → Actions → Runners](https://github.com/mrjamesmyers/omarchy-gremlins/settings/actions/runners).

## `smoke-test.sh` — the half CI cannot do

Runs each plugin's helper against real hardware and reports what it actually
found: printers, audio streams, cast targets. Read-only. Run it on an Omarchy
machine with the devices you care about on the same network.

## `split-plugin.sh` — publishing

`omarchy plugin add` wants `manifest.json` at the repository root, so a plugin
cannot be installed from a subdirectory of this repo. This does the
`git subtree split` into a standalone repo with history intact.
