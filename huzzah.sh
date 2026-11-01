#!/usr/bin/env bash
# Manage an Adafruit Feather Huzzah ESP8266: files with ampy, flashing with esptool, both from esptool-env.
#
# Usage:
#   huzzah.sh port                           Show the detected serial port
#   huzzah.sh ls [-l] [remote_dir]           List files on the board
#   huzzah.sh get remote [local]             Download a file (stdout if no local)
#   huzzah.sh put local [remote]             Upload a file
#   huzzah.sh load                           Copy everything in device/ to the board
#   huzzah.sh rm remote                      Delete a file
#   huzzah.sh mkdir remote                   Create a directory
#   huzzah.sh rmdir remote                   Remove a directory
#   huzzah.sh run script.py                  Run a local script on the board
#   huzzah.sh reset                          Hard reset the board (esptool run)
#   huzzah.sh erase                          Erase all flash (asks to confirm)
#   huzzah.sh flash [firmware.bin]           Erase, then flash CircuitPython (asks to confirm)
#   huzzah.sh wifi set ssid password [name]  Save WiFi credentials and the board's network name (wifi_config.py)
#   huzzah.sh wifi clear                     Delete the saved WiFi credentials
#   huzzah.sh wifi scan                      Pick an access point in range, then save its password
#
# Run a command with --help, or without its required arguments, to see an example.
# The port is found via /dev/cu.usbserial*. Override with AMPY_PORT or -p.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_PYTHON="$SCRIPT_DIR/esptool-env/bin/python"
PORT_GLOB="/dev/cu.usbserial*"
EXAMPLE_FILE="$SCRIPT_DIR/examples/bme280_simple.py"
DEVICE_DIR="$SCRIPT_DIR/device"
DEFAULT_FIRMWARE="$SCRIPT_DIR/firmware/adafruit-circuitpython-feather_huzzah-3.1.2.bin"

die() {
    echo "error: $*" >&2
    exit 1
}

print_usage() {
    sed -n '2,/^$/p' "$0" | sed '$d' | sed 's/^# \{0,1\}//'
}

# Example invocation for a command, using bme280_simple.py as the local file.
example_for() {
    case "$1" in
        port)  echo "$0 port" ;;
        ls)    echo "$0 ls lib" ;;
        get)   echo "$0 get code.py ./code.py" ;;
        put)   echo "$0 put $EXAMPLE_FILE code.py" ;;
        load)  echo "$0 load" ;;
        rm)    echo "$0 rm code.py" ;;
        mkdir) echo "$0 mkdir lib" ;;
        rmdir) echo "$0 rmdir lib" ;;
        run)   echo "$0 run $EXAMPLE_FILE" ;;
        reset) echo "$0 reset" ;;
        erase) echo "$0 erase" ;;
        flash) echo "$0 flash firmware.bin" ;;
        wifi)  echo "$0 wifi set MyNetwork mypassword" ;;
    esac
}

show_example() {
    echo "example:"
    echo "  $(example_for "$1")"
}

# need_args <command> <message>: report missing arguments with an example, then exit.
need_args() {
    echo "error: $2" >&2
    show_example "$1" >&2
    exit 1
}

find_port() {
    if [[ -n "${AMPY_PORT:-}" ]]; then
        echo "$AMPY_PORT"
        return
    fi

    local ports=()
    local p
    for p in $PORT_GLOB; do
        [[ -e "$p" ]] && ports+=("$p")
    done

    case ${#ports[@]} in
        0) die "no device matching $PORT_GLOB found. Is the Huzzah plugged in?" ;;
        1) echo "${ports[0]}" ;;
        *)
            echo "multiple serial ports found:" >&2
            printf '  %s\n' "${ports[@]}" >&2
            die "set AMPY_PORT to choose one"
            ;;
    esac
}

if [[ $# -lt 1 ]]; then
    print_usage
    exit 1
fi

if [[ "$1" == "-h" || "$1" == "--help" ]]; then
    print_usage
    exit 0
fi

cmd="$1"
shift

case "$cmd" in
    port|ls|get|put|load|rm|mkdir|rmdir|run|reset|erase|flash|wifi) ;;
    *) die "unknown command: $cmd (see $0 --help)" ;;
esac

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
    show_example "$cmd"
    exit 0
fi

[[ -x "$VENV_PYTHON" ]] || die "venv python not found at $VENV_PYTHON (run ./setup.sh)"

if [[ "$cmd" == "port" ]]; then
    find_port
    exit 0
fi

PORT="$(find_port)"

# ampy's entry-point script in esptool-env has a stale shebang, so run it as a module.
ampy() {
    "$VENV_PYTHON" -m ampy.cli --port "$PORT" "$@"
}

# ampy's get/put/run need ubinascii, which CircuitPython lacks, so transfers use mpremote.
# "resume" skips mpremote's soft reset, and the sleep gives CircuitPython time to reach the REPL.
mp() {
    "$VENV_PYTHON" -m mpremote connect "$PORT" resume sleep 2 "$@"
}

# esp: run esptool against the board's serial port at 460800 baud.
esp() {
    "$VENV_PYTHON" -m esptool --port "$PORT" --baud 460800 "$@"
}

# confirm <message>: ask before anything that wipes the board. Anything but "y" aborts.
confirm() {
    local answer
    read -r -p "$1 [y/N] " answer || answer=""
    [[ "$answer" == "y" || "$answer" == "Y" ]] || die "aborted"
}

do_erase() {
    confirm "Erase all flash on $PORT? This deletes every file on the board."
    esp erase-flash
}

do_flash() {
    local firmware="${1:-$DEFAULT_FIRMWARE}"
    [[ -f "$firmware" ]] || die "firmware not found: $firmware"
    confirm "Erase $PORT and flash $(basename "$firmware")? This deletes every file on the board."
    esp erase-flash
    esp write-flash --flash-size detect 0x0 "$firmware"
}

do_get() {
    local remote="$1" local_path="${2:-}"
    if [[ -n "$local_path" ]]; then
        mp fs cp ":$remote" "$local_path"
        return
    fi

    # No local path: copy to a temp file and print it to stdout. mpremote's status line goes to stderr.
    local tmp
    tmp="$(mktemp)"
    mp fs cp ":$remote" "$tmp" >&2
    cat "$tmp"
    rm -f "$tmp"
}

do_put() {
    local local_file="$1" remote="${2:-$(basename "$1")}"
    # mpremote's copy fails when the target doesn't exist yet, so create it first.
    # Append mode creates the file without truncating an existing one.
    mp exec "open('$remote', 'a').close()" >/dev/null
    mp fs cp "$local_file" ":$remote"
}

# Copy everything under device/ to the board root, keeping the folder layout (lib/ and its packages).
# Existing files are overwritten. Nothing on the board is deleted.
do_load() {
    [[ -d "$DEVICE_DIR" ]] || die "device folder not found: $DEVICE_DIR"

    local rel
    local dirs=()
    local files=()
    while IFS= read -r rel; do dirs+=("${rel#./}"); done < <(cd "$DEVICE_DIR" && find . -mindepth 1 -type d -not -name __pycache__ | sort)
    while IFS= read -r rel; do files+=("${rel#./}"); done < <(cd "$DEVICE_DIR" && find . -type f -name '*.py' | sort)

    # Sorting puts each parent folder before its children. mkdir fails if the folder is already on the board, which is fine.
    for rel in ${dirs[@]+"${dirs[@]}"}; do
        mp fs mkdir ":$rel" >/dev/null 2>&1 || true
    done
    for rel in ${files[@]+"${files[@]}"}; do
        echo "copying $rel"
        do_put "$DEVICE_DIR/$rel" "$rel"
    done
    echo "loaded ${#files[@]} files. Run ./huzzah.sh reset to start them."
}

# The WiFi credentials live in wifi_config.py on the board, so they never go in the repo.
WIFI_CONFIG="wifi_config.py"

# valid_hostname <name>: a DHCP hostname of 1-63 letters, digits or hyphens, not starting or ending with a hyphen.
valid_hostname() {
    [[ "$1" =~ ^[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?$ ]]
}

# ask_hostname: prompt for the name the board shows on the network, defaulting to "enviro". Prints the name.
ask_hostname() {
    local name
    while true; do
        read -r -p "name for the board on the network [enviro]: " name || name=""
        name="${name:-enviro}"
        if valid_hostname "$name"; then
            echo "$name"
            return
        fi
        echo "use 1-63 letters, digits or hyphens, not starting or ending with a hyphen" >&2
    done
}

# do_wifi_set <ssid> <password> <name>: write the credentials and the board's name as Python string literals,
# so quotes and backslashes are escaped. They go in through stdin, not argv, so the password doesn't show up in the process list.
do_wifi_set() {
    local ssid="$1" password="$2" name="$3"
    local tmp
    tmp="$(mktemp)"
    printf '%s\n%s\n%s\n' "$ssid" "$password" "$name" | "$VENV_PYTHON" -c '
import sys
ssid, password, name = sys.stdin.read().split("\n")[:3]
print("SSID = %r" % ssid)
print("PASSWORD = %r" % password)
print("HOSTNAME = %r" % name)
' > "$tmp"
    # Delete the local copy of the password whether or not the upload works
    do_put "$tmp" "$WIFI_CONFIG" || { rm -f "$tmp"; die "could not write $WIFI_CONFIG to the board"; }
    rm -f "$tmp"
    echo "saved WiFi credentials for $ssid and board name $name to $WIFI_CONFIG on the board"
}

# do_wifi_scan: scan on the board, let the user pick a network, ask for its password, then save it.
# Results come back as "AP <rssi> <authmode> <ssid>" lines from examples/wifi_scan.py.
do_wifi_scan() {
    local scan_out line tag rssi auth ssid choice idx password name
    local ssids=() rssis=() auths=()
    scan_out="$(mktemp)"

    echo "scanning..." >&2
    mp run "$SCRIPT_DIR/examples/wifi_scan.py" > "$scan_out" || { rm -f "$scan_out"; die "scan failed"; }
    while IFS= read -r line; do
        line="${line%$'\r'}"
        [[ "$line" == AP\ * ]] || continue
        # The SSID is last, so read takes the rest of the line for it, spaces included
        read -r tag rssi auth ssid <<< "$line"
        ssids+=("$ssid")
        rssis+=("$rssi")
        auths+=("$auth")
    done < "$scan_out"
    rm -f "$scan_out"

    [[ ${#ssids[@]} -gt 0 ]] || die "no access points found"

    echo "access points in range, strongest first:"
    for idx in "${!ssids[@]}"; do
        local open=""
        [[ "${auths[$idx]}" == 0 ]] && open="  (open)"
        printf '  %2d) %s  %s dBm%s\n' "$((idx + 1))" "${ssids[$idx]}" "${rssis[$idx]}" "$open"
    done

    while true; do
        read -r -p "select a network [1-${#ssids[@]}], or q to quit: " choice || choice="q"
        case "$choice" in
            q|Q) die "aborted" ;;
            *)
                if [[ "$choice" =~ ^[0-9]+$ ]] && (( choice >= 1 && choice <= ${#ssids[@]} )); then
                    break
                fi
                echo "enter a number from 1 to ${#ssids[@]}, or q" >&2
                ;;
        esac
    done

    idx=$((choice - 1))
    ssid="${ssids[$idx]}"
    password=""
    if [[ "${auths[$idx]}" != 0 ]]; then
        # Silent read, so the password isn't echoed on screen
        read -r -s -p "password for $ssid: " password || password=""
        echo >&2
        [[ -n "$password" ]] || die "no password entered for $ssid"
    fi
    name="$(ask_hostname)"
    do_wifi_set "$ssid" "$password" "$name"
}

do_wifi() {
    local sub="${1:-}"
    [[ $# -gt 0 ]] && shift
    case "$sub" in
        set)
            [[ $# -eq 2 || $# -eq 3 ]] || need_args wifi "wifi set needs an SSID and a password, and optionally a name"
            local name
            if [[ $# -eq 3 ]]; then
                valid_hostname "$3" || die "invalid name: $3 (use 1-63 letters, digits or hyphens, not starting or ending with a hyphen)"
                name="$3"
            else
                name="$(ask_hostname)"
            fi
            do_wifi_set "$1" "$2" "$name"
            ;;
        clear)
            mp fs rm ":$WIFI_CONFIG"
            echo "deleted $WIFI_CONFIG from the board"
            ;;
        scan)
            [[ $# -eq 0 ]] || need_args wifi "wifi scan takes no arguments"
            do_wifi_scan
            ;;
        *) need_args wifi "wifi needs a subcommand: set, clear or scan" ;;
    esac
}

case "$cmd" in
    ls)    ampy ls "$@" ;;
    get)   [[ $# -ge 1 ]] || need_args get "get needs a remote path"; do_get "$@" ;;
    put)   [[ $# -ge 1 ]] || need_args put "put needs a local path"; do_put "$@" ;;
    load)  do_load ;;
    rm)    [[ $# -eq 1 ]] || need_args rm "rm needs one remote path"; ampy rm "$1" ;;
    mkdir) [[ $# -eq 1 ]] || need_args mkdir "mkdir needs one remote path"; ampy mkdir "$1" ;;
    rmdir) [[ $# -eq 1 ]] || need_args rmdir "rmdir needs one remote path"; ampy rmdir "$1" ;;
    run)   [[ $# -eq 1 ]] || need_args run "run needs one local script"; mp run "$1" ;;
    reset) esp run ;;
    erase) do_erase ;;
    flash) do_flash "$@" ;;
    wifi)  do_wifi "$@" ;;
esac
