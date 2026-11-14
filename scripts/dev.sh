#!/usr/bin/env bash
# usage: scripts/dev.sh start|stop|status   (no --reload, to keep the laptop light)
cd "$(dirname "$0")/.."
SERVICES="page:8000 store:8001 catalog:8002 inventory:8003 search:8004 cart:8005 pricing:8006 draft-order:8007 order:8008 payment:8009"
case "${1:-start}" in
  start)
    for s in $SERVICES; do n=${s%%:*}; p=${s##*:}
      (cd "services/$n" && set -a && source ../../.env && set +a && exec uvicorn app.main:app --port "$p") > "/tmp/$n.log" 2>&1 &
    done
    sleep 6; "$0" status ;;
  stop) pkill -f uvicorn || true ;;
  status)
    for s in $SERVICES; do n=${s%%:*}; p=${s##*:}
      if curl -s -o /dev/null "localhost:$p/docs"; then echo "up    $n :$p"; else echo "DOWN  $n :$p (see /tmp/$n.log)"; fi
    done ;;
esac
