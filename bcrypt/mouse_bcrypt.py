#!/usr/bin/env python3

import hashlib
import hmac
import os
import secrets
import sys
import time
import tkinter as tk

try:
    import bcrypt
except ImportError:
    sys.exit("Please install first: pip install bcrypt")

REQUIRED_EVENTS = 250
PASSWORD_LENGTH_BYTES = 70
BCRYPT_ROUNDS = 12
OUTPUT_FILE = None


class EntropyCollector:
    def __init__(self):
        self._pool = hashlib.sha256()
        self._pool.update(os.urandom(64))
        self.count = 0

    def feed_mouse_event(self, x: int, y: int) -> None:
        data = f"{x}:{y}:{time.perf_counter_ns()}".encode()
        self._pool.update(data)
        self._pool.update(os.urandom(4))
        self.count += 1

    def derive_password_bytes(self, length: int) -> bytes:
        prk = self._pool.digest()
        okm = b""
        prev = b""
        counter = 1
        while len(okm) < length:
            prev = hmac.new(prk, prev + counter.to_bytes(1, "big"), hashlib.sha256).digest()
            okm += prev
            counter += 1
        return okm[:length]

    def wipe(self) -> None:
        self._pool = None


def run_gui_collection() -> EntropyCollector:
    collector = EntropyCollector()

    MIN_DISTANCE_PX = 3
    MIN_INTERVAL_S = 0.01

    root = tk.Tk()
    root.title("Move the mouse for entropy...")

    w, h = 500, 320
    sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
    root.geometry(f"{w}x{h}+{(sw - w)//2}+{(sh - h)//2}")

    state = {"started": False, "last_x": None, "last_y": None, "last_t": 0.0}

    label = tk.Label(
        root,
        text="Click 'Start' first, then move the mouse wildly",
        wraplength=460, justify="center", pady=15
    )
    label.pack()

    progress_var = tk.StringVar(value=f"0 / {REQUIRED_EVENTS}")
    progress_label = tk.Label(root, textvariable=progress_var, font=("Helvetica", 14))
    progress_label.pack(pady=5)

    canvas = tk.Canvas(root, bg="black", height=100)
    canvas.pack(fill="x", padx=20, pady=10)

    def start_collection():
        state["started"] = True
        start_button.config(state="disabled", text="Collecting entropy...")

    start_button = tk.Button(root, text="Start", command=start_collection, font=("Helvetica", 12))
    start_button.pack(pady=5)

    def on_motion(event):
        if not state["started"]:
            return

        now = time.perf_counter()
        if state["last_x"] is not None:
            dx = event.x - state["last_x"]
            dy = event.y - state["last_y"]
            dist_sq = dx * dx + dy * dy
            if dist_sq < MIN_DISTANCE_PX ** 2 or (now - state["last_t"]) < MIN_INTERVAL_S:
                return

        state["last_x"], state["last_y"], state["last_t"] = event.x, event.y, now

        collector.feed_mouse_event(event.x, event.y)
        progress_var.set(f"{collector.count} / {REQUIRED_EVENTS}")
        canvas.delete("dot")
        canvas.create_oval(event.x - 3, 20, event.x + 3, 26, fill="lime", tags="dot")
        if collector.count >= REQUIRED_EVENTS:
            root.destroy()

    root.bind("<Motion>", on_motion)
    root.mainloop()

    return collector


def main():
    print("== Password generation via mouse entropy ==")
    print(f"Move mouse {REQUIRED_EVENTS} times...")

    collector = run_gui_collection()

    if collector.count < REQUIRED_EVENTS:
        sys.exit("Aborted - not enough entropy collected.")

    password_bytes = collector.derive_password_bytes(PASSWORD_LENGTH_BYTES)
    collector.wipe()

    salt = bcrypt.gensalt(rounds=BCRYPT_ROUNDS)
    hashed = bcrypt.hashpw(password_bytes, salt)

    password_bytes = secrets.token_bytes(len(password_bytes))  # overwrite variable
    del password_bytes

    print("\nDone! The plaintext password was never displayed.")
    print("bcrypt hash:")
    print(hashed.decode())

    if OUTPUT_FILE:
        with open(OUTPUT_FILE, "w") as f:
            f.write(hashed.decode() + "\n")
        print(f"\nHash also saved to: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()