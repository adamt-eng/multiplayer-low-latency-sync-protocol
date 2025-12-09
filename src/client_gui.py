import tkinter as tk
from typing import Optional
import constants


root: Optional[tk.Tk] = None
canvas: Optional[tk.Canvas] = None

grid = None
sock = None
player_id_ref = None
send_acquire_request = None

GRID_SIZE = constants.GRID_SIZE
CELL_SIZE = constants.CELL_SIZE

MY_COLOR = "#4C84FF"
ENEMY_COLOR = "#FF4C4C"
UNCLAIMED_COLOR = "#CCCCCC"

def init_gui(shared_grid, shared_sock, shared_player_id_ref, send_func):
    global grid, sock, player_id_ref, send_acquire_request
    grid = shared_grid
    sock = shared_sock
    player_id_ref = shared_player_id_ref
    send_acquire_request = send_func


def draw_grid():
    if canvas is None:
        return

    canvas.delete("all")
    my_id = player_id_ref[0]  # type: ignore # my assigned ID

    for r in range(GRID_SIZE):
        for c in range(GRID_SIZE):
            cell = grid[(r, c)] # type: ignore
            owner = cell.get("owner")

            # Determine color
            if owner is None:
                color = UNCLAIMED_COLOR
            elif owner == my_id:
                color = MY_COLOR
            else:
                color = ENEMY_COLOR

            x0 = c * CELL_SIZE
            y0 = r * CELL_SIZE
            x1 = x0 + CELL_SIZE
            y1 = y0 + CELL_SIZE

            # Draw colored box
            canvas.create_rectangle(x0, y0, x1, y1, fill=color, outline="black")

            # Draw owner ID number centered
            if owner is not None:
                canvas.create_text(
                    (x0 + x1) / 2,
                    (y0 + y1) / 2,
                    text=str(owner),
                    fill="white" if color != UNCLAIMED_COLOR else "black",
                    font=("Arial", int(CELL_SIZE * 0.4), "bold")
                )


def start_gui():
    if root:
        root.mainloop()


def setup_gui():
    global root, canvas

    root = tk.Tk()
    root.title("Grid Clash")

    canvas = tk.Canvas(root, width=GRID_SIZE * CELL_SIZE, height=GRID_SIZE * CELL_SIZE)
    canvas.pack()

    def on_click(event):
        pid = player_id_ref[0] # type: ignore
        if pid is None:
            return
        r, c = event.y // CELL_SIZE, event.x // CELL_SIZE
        send_acquire_request(sock, pid, (r, c)) # type: ignore

    canvas.bind("<Button-1>", on_click)

    draw_grid()


def update_grid():
    if root:
        root.after(0, draw_grid)


def update_window_title(pid: str):
    if root:
        root.after(0, lambda: root.title(f"Grid Clash — Player {pid}")) # type: ignore
