"""Drawing for the keys, and for the touch strip (Stream Deck+) or small screen (Neo)."""

import functools

from PIL import Image, ImageDraw, ImageFont
from StreamDeck.ImageHelpers import PILHelper

from scoring import MISS, PERFECT

DESIGN_SIZE = 120  # sizes below are for 120-pixel keys and scale to the deck's own
TAP_COLOR = (235, 70, 70)
HOLD_COLOR = (190, 90, 255)
LOOSE_HOLD_COLOR = (110, 110, 125)  # a hold you've let go of but can still grab
UNUSED_COLOR = (45, 45, 52)  # keys a chart with fewer lanes doesn't use
STACK_SHADES = (1.0, 0.75, 0.55)  # from the back of a stack: bright, slightly dark, darker, repeating
NOTE_BORDER_COLOR = (255, 255, 255)
NOTE_BORDER_WIDTH = 2
NOTE_CORNER_SHARE = 0.12  # corner radius as a share of the box's size, so corners grow with it
SIZE_STEP = 4  # boxes grow in even steps, which keeps them centered and sends fewer images
RESULT_TEXT_STEPS = 10  # fade frames; fewer means fewer images sent to the device
RESULT_TEXT_SHRINK = 0.4  # the text ends this much smaller than it starts
MISS_TEXT_COLOR = (235, 60, 60)
LABEL_COLOR = (160, 160, 175)
QUIT_COLOR = (220, 60, 60)
QUIT_PRESSED_FILL = (70, 15, 15)
QUIT_TAPS = 3
FRAME_CACHE_LIMIT = 5000


def font(size):
    return _font(max(6, round(size)))


@functools.cache
def _font(size):
    return ImageFont.load_default(size=size)


def fitted_font(text, size, width):
    """The largest font up to `size` that fits `text` in `width` pixels."""
    while size > 6 and font(size).getlength(text) > width:
        size -= 1
    return font(size)


def note_color(is_hold, place):
    shade = STACK_SHADES[place % len(STACK_SHADES)]
    return tuple(round(c * shade) for c in (HOLD_COLOR if is_hold else TAP_COLOR))


def draw_quit(draw, box, taps, scale):
    left, top, right, bottom = box
    draw.rounded_rectangle(box, radius=12 * scale, outline=QUIT_COLOR, width=max(1, round(3 * scale)),
                           fill=QUIT_PRESSED_FILL if taps else "black")
    middle = (left + right) / 2
    draw.text((middle, top + (bottom - top) * 0.38), "QUIT", font=font(28 * scale), fill="white", anchor="mm")
    # One dot per tap needed; filled ones show taps so far
    for i in range(QUIT_TAPS):
        x = middle + (i - (QUIT_TAPS - 1) / 2) * 22 * scale
        y = top + (bottom - top) * 0.76
        r = 6 * scale
        draw.ellipse((x - r, y - r, x + r, y + r), fill=QUIT_COLOR if i < taps else None, outline=QUIT_COLOR,
                     width=max(1, round(2 * scale)))


class KeyArt:
    """Turns a key's state into the image the deck wants, caching repeats."""

    def __init__(self, deck):
        self.deck = deck
        self.width, self.height = deck.key_image_format()["size"]
        self.box = min(self.width, self.height)  # notes are squares that fit the key
        self.scale = self.box / DESIGN_SIZE
        self.label_font_size = fitted_font(PERFECT, 30 * self.scale, self.width - 14 * self.scale).size
        self.cache = {}

    def box_pixels(self, fraction):
        return round(fraction * self.box / SIZE_STEP) * SIZE_STEP

    def drain_pixels(self, fraction):
        return round(fraction * self.height / SIZE_STEP) * SIZE_STEP

    def frame(self, state):
        """The deck-ready image for a key state; Game.key_states lists the shapes states take."""
        if state in self.cache:
            return self.cache[state]
        if len(self.cache) > FRAME_CACHE_LIMIT:
            self.cache.clear()
        image = PILHelper.create_key_image(self.deck)
        draw = ImageDraw.Draw(image)
        kind = state[0] if state else None
        if kind == "unused":
            draw.rectangle((0, 0, self.width, self.height), fill=UNUSED_COLOR)
        elif kind == "quit":
            s = self.scale
            draw_quit(draw, (8 * s, self.height / 2 - 38 * s, self.width - 8 * s, self.height / 2 + 38 * s), state[1], s)
        elif kind == "drain":
            _, filled, held, stack, _ = state
            if filled > 0:
                color = note_color(True, 0) if held else LOOSE_HOLD_COLOR
                draw.rectangle((0, self.height - filled, self.width, self.height), fill=color)
            self.draw_stack(draw, stack)
        elif kind == "note":
            _, side, is_hold, stack, _ = state
            self.draw_box(draw, side, note_color(is_hold, 0))
            self.draw_stack(draw, stack)
        if kind in ("label", "drain", "note") and state[-1]:
            image = self.draw_label(image, *state[-1])
        frame = PILHelper.to_native_key_format(self.deck, image)
        self.cache[state] = frame
        return frame

    def draw_box(self, draw, side, color):
        if side <= 0:
            return
        left = (self.width - side) // 2
        top = (self.height - side) // 2
        box = (left, top, left + side - 1, top + side - 1)
        draw.rounded_rectangle(box, radius=round(side * NOTE_CORNER_SHARE), fill=color,
                               outline=NOTE_BORDER_COLOR, width=NOTE_BORDER_WIDTH)

    def draw_stack(self, draw, stack):
        for side, is_hold, place in stack:
            self.draw_box(draw, side, note_color(is_hold, place))

    def draw_label(self, image, result, step):
        fade = step / RESULT_TEXT_STEPS
        alpha = round(255 * (1 - fade))
        color = MISS_TEXT_COLOR if result == MISS else (255, 255, 255)
        # Drawn on its own layer so it can fade over whatever the key shows
        layer = Image.new("RGBA", image.size, (0, 0, 0, 0))
        ImageDraw.Draw(layer).text(
            (self.width / 2, self.height / 2), result, anchor="mm",
            font=font(self.label_font_size * (1 - RESULT_TEXT_SHRINK * fade)),
            fill=(*color, alpha), stroke_width=max(1, round(3 * self.scale)), stroke_fill=(0, 0, 0, alpha),
        )
        return Image.alpha_composite(image.convert("RGBA"), layer).convert("RGB")

    def tile(self, rows):
        """A results key: one (label, value) row, or two sharing the key."""
        image = PILHelper.create_key_image(self.deck)
        draw = ImageDraw.Draw(image)
        # (label height, value height, biggest value size) as shares of the key
        spots = [(0.22, 0.62, 48)] if len(rows) == 1 else [(0.13, 0.33, 30), (0.60, 0.80, 30)]
        for (label, value), (label_y, value_y, size) in zip(rows, spots):
            x = self.width / 2
            label_font = fitted_font(label, 18 * self.scale, self.width - 6)
            draw.text((x, self.height * label_y), label, font=label_font, fill=LABEL_COLOR, anchor="mm")
            value_font = fitted_font(value, size * self.scale, self.width - 12 * self.scale)
            color = MISS_TEXT_COLOR if label == MISS else "white"
            draw.text((x, self.height * value_y), value, font=value_font, fill=color, anchor="mm")
        return PILHelper.to_native_key_format(self.deck, image)


class StatusPanel:
    """Live stats on the Stream Deck+'s touch strip, with a QUIT button, or on the Neo's small screen."""

    def __init__(self, deck):
        self.deck = deck
        self.touch = deck.is_touch()
        size = deck.touchscreen_image_format()["size"] if self.touch else deck.screen_image_format()["size"]
        self.width, self.height = size
        self.scale = self.height / 100  # laid out for the Plus's 100-pixel-tall strip
        s = self.scale
        self.quit_button = None
        if self.touch:
            self.quit_button = (self.width - 170 * s, 12 * s, self.width - 12 * s, 88 * s)
        self.sent = None

    def hits_quit(self, x):
        return self.quit_button is not None and self.quit_button[0] <= x <= self.quit_button[2]

    def show_stats(self, result, combo, accuracy, misses, taps):
        state = (result, combo, accuracy, misses, taps)
        if state == self.sent:
            return
        self.sent = state
        image, draw = self.blank()
        s = self.scale
        right = self.quit_button[0] if self.quit_button else self.width
        middle = right / 2
        result_font = fitted_font(result, 38 * s, right - 8)
        draw.text((middle, self.height * 0.32), result, font=result_font, fill=MISS_TEXT_COLOR if result == MISS else "white",
                  anchor="mm")
        stats = [(f"Combo {combo}", "white"), (f"{accuracy:.2f}%", "white"), (f"Misses {misses}", MISS_TEXT_COLOR)]
        gap = 36 * s
        stats_font = fitted_font("   ".join(text for text, _ in stats), 26 * s, right - 8 - 2 * gap)
        x = middle - (sum(stats_font.getlength(text) for text, _ in stats) + gap * (len(stats) - 1)) / 2
        for text, color in stats:
            draw.text((x, self.height * 0.76), text, font=stats_font, fill=color, anchor="lm")
            x += stats_font.getlength(text) + gap
        if self.quit_button:
            draw_quit(draw, self.quit_button, taps, s)
        self.send(image)

    def show_message(self, text):
        image, draw = self.blank()
        draw.text((self.width / 2, self.height / 2), text, font=fitted_font(text, 38 * self.scale, self.width - 16),
                  fill=LABEL_COLOR, anchor="mm")
        self.send(image)

    def blank(self):
        image = PILHelper.create_touchscreen_image(self.deck) if self.touch else PILHelper.create_screen_image(self.deck)
        return image, ImageDraw.Draw(image)

    def send(self, image):
        with self.deck:
            if self.touch:
                native = PILHelper.to_native_touchscreen_format(self.deck, image)
                self.deck.set_touchscreen_image(native, 0, 0, self.width, self.height)
            else:
                self.deck.set_screen_image(PILHelper.to_native_screen_format(self.deck, image))
