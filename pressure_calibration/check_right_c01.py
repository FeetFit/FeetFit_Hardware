import time
import statistics

from hardware import pressure as p


def read_snapshot():
    scans = []

    for i in range(3):
        left, right = p.read_both_feet()
        scans.append((left, right))
        print(f"Scan {i + 1}/3 completed", flush=True)

    result = []

    for side in (0, 1):
        values = []

        for ch in range(p.CHANNEL_COUNT):
            samples = [scan[side][ch] for scan in scans]
            values.append(statistics.median(samples))

        result.append(values)

    return result


print("=" * 60)
print("USER RIGHT C01 - LEFT/RIGHT MAPPING TEST")
print("=" * 60)

print(f"Software LEFT  : GPIO{p.EN_LEFT}")
print(f"Software RIGHT : GPIO{p.EN_RIGHT}")

try:
    with p.pressure_lock:

        print("\nSTEP 1: NO LOAD")
        input("Remove all weights, then press ENTER: ")

        before = read_snapshot()

        print("\nSTEP 2: USER RIGHT C01")
        print("Place 1kg weight on USER RIGHT C01.")
        input("Keep weight in place and press ENTER: ")

        print("Measuring... Do not move the weight.")
        time.sleep(1)

        after = read_snapshot()

finally:
    p.disable_muxes()


print("\n" + "=" * 60)
print("MAPPING CHECK RESULT")
print("=" * 60)

for side, name in enumerate(("LEFT", "RIGHT")):

    delta = [
        after[side][i] - before[side][i]
        for i in range(p.CHANNEL_COUNT)
    ]

    peak = max(
        range(p.CHANNEL_COUNT),
        key=lambda i: delta[i]
    )

    print(f"\n{name}")
    print(f"C01 change : {delta[1]:.1f} ADC")
    print(
        f"Largest change : "
        f"C{peak:02d} = {delta[peak]:.1f} ADC"
    )

print("\nTEST COMPLETED")
