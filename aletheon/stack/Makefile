# Root promotion of the enforcement surface (DESIGN.md §4.4): `sudo make install` copies
# the runner/recovery/privileged helpers OUT of leo's write set. Claude-as-leo can edit the
# repo sources, but root re-promotes them only when Leo deliberately runs this.
PREFIX     := /usr/local
SUDOERS    := /etc/sudoers.d/aletheon
USER_NAME  := leo
DATASETS   := blazing/stack blazing/modes-assets

.PHONY: install install-bins install-sudoers install-zfs-delegation install-syncoid uninstall check

install: check install-bins install-sudoers install-zfs-delegation install-syncoid
	@echo "install complete — re-run after any deliberate change to bin/{overhaulctl,powerguard-shed,chrome-theme}"

check:
	@test "$$(id -u)" = 0 || { echo "run as root: sudo make install"; exit 1; }
	python3 -m py_compile bin/overhaulctl bin/watcherd bin/modectl bin/fx bin/simrun \
	  bin/hook-signal bin/wallpaper_driver.py
	bash -n bin/chrome-theme bin/powerguard-shed bin/powerguard-session \
	  bin/preflight.sh bin/kiosk-recycle-check bin/probe-kiosk-pingback bin/probe-applied-config

install-bins:
	install -m 755 -o root -g root bin/overhaulctl      $(PREFIX)/bin/overhaulctl
	install -m 755 -o root -g root bin/powerguard-shed  $(PREFIX)/sbin/powerguard-shed
	install -m 755 -o root -g root bin/chrome-theme     $(PREFIX)/sbin/chrome-theme

install-sudoers:
	# nut's upssched runs as the nut user and must shed load as root (§3.5 — review);
	# the leo pin covers the phase-0 shed test. Wire NUT: upssched.conf CMDSCRIPT =
	# /usr/local/sbin/powerguard-shed via `sudo` (see setup/nut-upssched.conf.sample).
	printf '%s\n' \
	  '$(USER_NAME) ALL=(root) NOPASSWD: $(PREFIX)/sbin/chrome-theme' \
	  '$(USER_NAME) ALL=(root) NOPASSWD: $(PREFIX)/sbin/powerguard-shed' \
	  'nut ALL=(root) NOPASSWD: $(PREFIX)/sbin/powerguard-shed' \
	  > $(SUDOERS).tmp
	visudo -cf $(SUDOERS).tmp
	install -m 440 -o root -g root $(SUDOERS).tmp $(SUDOERS)
	rm -f $(SUDOERS).tmp

install-zfs-delegation:
	# snapshot/clone/mount/hold ONLY — destroy/rollback stay root (§4.4)  [TEST]
	for ds in $(DATASETS); do zfs allow -u $(USER_NAME) snapshot,clone,mount,hold $$ds; done

install-syncoid:
	# root-owned replication leo cannot touch (§3.8): stack+modes snapshots → tank/backup
	printf '%s\n' '[Unit]' 'Description=aletheon snapshot replication' \
	  '[Service]' 'Type=oneshot' \
	  'ExecStart=/usr/sbin/syncoid --no-sync-snap blazing/stack tank/backup/stack' \
	  'ExecStart=/usr/sbin/syncoid --no-sync-snap blazing/modes-assets tank/backup/modes-assets' \
	  > /etc/systemd/system/aletheon-syncoid.service
	printf '%s\n' '[Unit]' 'Description=aletheon replication timer' \
	  '[Timer]' 'OnCalendar=daily' 'Persistent=true' \
	  '[Install]' 'WantedBy=timers.target' \
	  > /etc/systemd/system/aletheon-syncoid.timer
	systemctl daemon-reload
	systemctl enable --now aletheon-syncoid.timer

uninstall:
	rm -f $(PREFIX)/bin/overhaulctl $(PREFIX)/sbin/powerguard-shed $(PREFIX)/sbin/chrome-theme $(SUDOERS)
	systemctl disable --now aletheon-syncoid.timer || true
	rm -f /etc/systemd/system/aletheon-syncoid.{service,timer}
	systemctl daemon-reload
