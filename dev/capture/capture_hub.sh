#!/bin/sh
# dev/capture/capture_hub.sh <seed_demo|seed_tour> -- fresh Alpine hub container for README
# image capture: real chronyd (so the header clock reads synced), hub on 8099,
# syslog on 5514/udp, then the given seed. Remove with: docker rm -f ct-capture
# Host port 8199, not 8099: other local lab containers report to whatever
# answers on 8099 and would show up in the images.
set -eu
SEED="$1"
docker rm -f ct-capture >/dev/null 2>&1 || true
MSYS_NO_PATHCONV=1 docker run -d --name ct-capture -p 8199:8099 -p 5514:5514/udp \
    -v "C:/tools/claude/confetti-traffic:/src:ro" alpine:3.22 sleep infinity >/dev/null
COMMIT=$(git -C C:/tools/claude/confetti-traffic rev-parse HEAD)
MSYS_NO_PATHCONV=1 docker exec -e COMMIT="$COMMIT" ct-capture sh -c '
    apk add --no-progress -q python3 py3-flask py3-waitress chrony >/dev/null
    mkdir -p /run/chrony /var/lib/confetti && chown chrony:chrony /run/chrony && chmod 750 /run/chrony
    chronyd -x
    mkdir -p /tmp/bundle && echo "commit=$COMMIT" > /tmp/bundle/RELEASE
    cd /src/hub && HUB_PORT=8099 HUB_SYSLOG_PORT=5514 HUB_DB_PATH=/var/lib/confetti/hub.db \
        HUB_KEY_DIR=/tmp/keys HUB_BUNDLE_DIR=/tmp/bundle nohup python3 serve.py >/tmp/hub.log 2>&1 &
'
i=0
until curl -s http://127.0.0.1:8199/api/time | grep -q '"synced": *true\|"synced":true'; do
    i=$((i + 1)); [ "$i" -gt 60 ] && { echo "clock never synced"; curl -s http://127.0.0.1:8199/api/time; exit 1; }
    sleep 2
done
echo "hub up, clock synced"
MSYS_NO_PATHCONV=1 docker exec -e SEED_DB=/var/lib/confetti/hub.db ct-capture python3 "/src/dev/capture/$SEED.py"
echo "seeded: $SEED"
