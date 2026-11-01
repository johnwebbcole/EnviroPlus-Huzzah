# Prints each access point in range, strongest first, as: AP <rssi> <authmode> <ssid>
# authmode 0 is an open network, so it needs no password. './huzzah.sh wifi scan' runs this and parses the AP lines.
import network

sta_if = network.WLAN(network.STA_IF)
sta_if.active(True)
found = {}
for ap in sta_if.scan():
    # CircuitPython 3.x bytes have no decode(), so build the text from the byte values
    ssid = "".join([chr(c) for c in ap[0]])
    # Skip names with control characters (0-31, 127-159). Any access point in range picks its own name, and these
    # could add fake lines to the list or send escape codes to the terminal. Use 'huzzah.sh wifi set' for such a network.
    if [c for c in ap[0] if c < 32 or 127 <= c < 160]:
        continue
    # Hidden networks report an empty SSID, and one SSID can come from several access points, so keep the strongest
    if ssid and (ssid not in found or ap[3] > found[ssid][0]):
        found[ssid] = (ap[3], ap[4])
for ssid in sorted(found, key=lambda s: -found[s][0]):
    print("AP", found[ssid][0], found[ssid][1], ssid)
