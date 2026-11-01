# Draws the graph from graph.History. Copied to the board as graph_draw.py, and imported by code.py after graph.py, so it
# compiles on its own: one large module needs more free heap than the ESP8266 has once the HTTP server is running.

from graph import SERIES, LABEL_X, LABEL_TOP_ROW, LABEL_BOTTOM_ROW, LABEL_CHARS, PLOT_RIGHT, PANEL_ROWS, decode, row_for, column_for

def draw_line(display, x0, y0, x1, y1, colour, top):
    # Joins two plot points with one run of pixels in each column, so the line has no gaps.
    # top is the controller row of panel row 0, which draw_text would otherwise add itself.
    prev = y0
    for x in range(x0, x1 + 1):
        y = y1 if x1 == x0 else y0 + (y1 - y0) * (x - x0) // (x1 - x0)
        display.fill_rect(x, top + min(prev, y), x, top + max(prev, y), colour)
        prev = y

def draw_graph(display, history):
    import gc
    import st7735
    # The panel fill builds a list the size of a row, which needs a free block of heap, so collect garbage first
    gc.collect()
    # Draws the whole graph, so it is only called when the graph view is entered or a new sample has been stored.
    # The bus is locked for the drawing, as in draw_cells.
    while not display.spi.try_lock():
        pass
    try:
        top = st7735.VISIBLE_ROW_OFFSET
        # Only the visible rows are cleared, which is all the panel shows
        display.fill_rect(0, top, PLOT_RIGHT, top + PANEL_ROWS - 1, 0x0000)
        if history.count == 0:
            display.draw_text(47, 30, "NO DATA YET", 0xFFFF)
            return
        for j, (colour, scale, offset, label) in enumerate(SERIES):
            # One pass over the samples finds this series' lowest and highest values
            lo = hi = history.value(0, j)
            for age in range(1, history.count):
                n = history.value(age, j)
                lo = min(lo, n)
                hi = max(hi, n)
            # The highest value goes in the top row and the lowest in the bottom row, both in the line's colour
            max_text = label % decode(hi, scale, offset)
            min_text = label % decode(lo, scale, offset)
            display.draw_text(LABEL_X[j], LABEL_TOP_ROW, max_text[:LABEL_CHARS], colour)
            display.draw_text(LABEL_X[j], LABEL_BOTTOM_ROW, min_text[:LABEL_CHARS], colour)
            # Joins the samples in time order, oldest first, so the newest sample is drawn last
            px = py = None
            for age in range(history.count - 1, -1, -1):
                x = column_for(age, history.count)
                y = row_for(history.value(age, j), lo, hi)
                if px is None:
                    px, py = x, y
                draw_line(display, px, py, x, y, colour, top)
                px, py = x, y
    finally:
        display.spi.unlock()
