#!/bin/sh
# Copy anyka_cfg.ini to writable flash to enable RTSP
if [ -f /mnt/anyka_cfg.ini ]; then
    cp /mnt/anyka_cfg.ini /etc/jffs2/anyka_cfg.ini
fi
# Start telnetd and ftp
telnetd &
tcpsvd 0 21 ftpd -w / &
# Reload anyka_ipc
killall -1 anyka_ipc
killall -HUP anyka_ipc
