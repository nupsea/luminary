#!/usr/bin/env sh
# Free a TCP port held by Luminary, for `make stop`, `make clean` and luminary.sh.
#
# Sourced for its free_port() function, or run directly:  sh scripts/free_port.sh 7820
#
# Two rules, each from real damage:
#
# 1. LISTENERS ONLY. `lsof -ti :PORT` matches every socket on the port, clients
#    included. A browser tab left on http://127.0.0.1:7820 holds a CLOSE_WAIT
#    socket and is returned by that query, so the old `make stop` would SIGTERM
#    -- then SIGKILL five seconds later -- the user's browser, while the app it
#    was asked to stop kept running. Observed with Brave at PID 718.
#    `-sTCP:LISTEN` is the fix, and the Ollama probe in the Makefile already
#    used it; stop and clean simply did not.
#
# 2. NEVER KILL THE PORT PROXY. With the app in Docker the host listener is
#    com.docker.backend, not uvicorn. Signalling it takes down Docker Desktop
#    for every project on the machine and leaves the container running, so the
#    app's own shutdown never happens. Stop the container instead -- that
#    delivers SIGTERM to PID 1, which is what runs the FastAPI lifespan.
#
# Killing whatever holds a resource is a pattern this repo has already paid for
# once: boot used to lsof the Kuzu graph file and SIGTERM the holder, which
# could only ever hit a live process mid-write. See backend/tests/test_graph_lock.py.
#
# SIGTERM first, always. SIGKILL cannot run the lifespan that stops the
# enrichment worker and cancels in-flight ingestion, and it is what leaves the
# Kuzu lock held against the next launch.
#
# The 30s grace is measured, not guessed. A full stop of the app container takes
# ~10.8s: the FastAPI lifespan itself finishes in well under a second, then the
# process sits in loop.run_until_complete cleaning up an unawaited LiteLLM
# coroutine (`BaseLLMHTTPHandler.async_completion`) before the interpreter exits.
# That is just over `docker stop`'s 10s default, so the default produced exit 137
# on one run and exit 0 on the next -- a SIGKILLed shutdown, at random, on the
# path users take every day. Both the container timeout and the native grace are
# set here so neither can drift back under the real number. A shorter value does
# not make stop faster: free_port returns the moment the port is released.

_fp_listeners() { lsof -tiTCP:"$1" -sTCP:LISTEN 2>/dev/null || true; }

_fp_cmd() { ps -p "$1" -o comm= 2>/dev/null | head -1; }

# Is this PID a port forwarder rather than the app itself?
_fp_is_proxy() {
    case "$(_fp_cmd "$1")" in
        *com.docker.backend*|*docker-proxy*|*vpnkit*) return 0 ;;
        *) return 1 ;;
    esac
}

# Stop the Luminary container publishing $1. Returns 0 stopped, 1 none found,
# 2 found but not ours (never stop a stranger's container to free a port).
_fp_stop_container() {
    _fpc_port="$1"
    command -v docker >/dev/null 2>&1 || return 1
    _fpc_row="$(docker ps --filter "publish=$_fpc_port" \
        --format '{{.ID}} {{.Names}} {{.Image}}' 2>/dev/null | head -1)"
    [ -n "$_fpc_row" ] || return 1
    _fpc_id="$(printf '%s' "$_fpc_row" | awk '{print $1}')"
    case "$_fpc_row" in
        *luminary*|*Luminary*)
            printf '  :%s is served by container %s — docker stop (graceful)\n' \
                "$_fpc_port" "$(printf '%s' "$_fpc_row" | awk '{print $2}')"
            docker stop -t "${FREE_PORT_GRACE:-30}" "$_fpc_id" >/dev/null 2>&1 && return 0
            return 1 ;;
        *)
            printf '  :%s is published by a NON-Luminary container (%s) — left alone.\n' \
                "$_fpc_port" "$(printf '%s' "$_fpc_row" | awk '{print $2}')"
            return 2 ;;
    esac
}

# free_port PORT [GRACE_SECONDS]
free_port() {
    _fp_port="$1"
    _fp_grace="${2:-${FREE_PORT_GRACE:-30}}"
    _fp_pids="$(_fp_listeners "$_fp_port")"

    if [ -z "$_fp_pids" ]; then
        printf '  :%s — nothing listening.\n' "$_fp_port"
        return 0
    fi

    for _fp_pid in $_fp_pids; do
        if _fp_is_proxy "$_fp_pid"; then
            _fp_stop_container "$_fp_port"
            case $? in
                0) return 0 ;;
                2) return 1 ;;
                *)
                    printf '  :%s is held by %s (a port proxy) but no Luminary\n' \
                        "$_fp_port" "$(_fp_cmd "$_fp_pid")"
                    printf '     container publishes it. Refusing to signal it — that would\n'
                    printf '     stop Docker itself. Check: docker ps --filter publish=%s\n' "$_fp_port"
                    return 1 ;;
            esac
        fi
    done

    printf '  :%s — SIGTERM to %s\n' "$_fp_port" "$(echo "$_fp_pids" | tr '\n' ' ')"
    for _fp_pid in $_fp_pids; do kill "$_fp_pid" 2>/dev/null || true; done

    _fp_waited=0
    while [ "$_fp_waited" -lt "$_fp_grace" ]; do
        sleep 1
        _fp_waited=$((_fp_waited + 1))
        [ -z "$(_fp_listeners "$_fp_port")" ] && {
            printf '  :%s — stopped cleanly after %ss.\n' "$_fp_port" "$_fp_waited"
            return 0
        }
    done

    _fp_pids="$(_fp_listeners "$_fp_port")"
    [ -z "$_fp_pids" ] && return 0
    printf '  :%s — still listening after %ss; SIGKILL to %s\n' \
        "$_fp_port" "$_fp_grace" "$(echo "$_fp_pids" | tr '\n' ' ')"
    printf '     (a forced kill can leave the Kuzu lock held; next start may report it)\n'
    for _fp_pid in $_fp_pids; do kill -9 "$_fp_pid" 2>/dev/null || true; done
    return 0
}

# Direct invocation: free every port given as an argument.
if [ "${0##*/}" = "free_port.sh" ] && [ "$#" -gt 0 ]; then
    for _fp_arg in "$@"; do free_port "$_fp_arg"; done
fi
