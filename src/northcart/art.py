"""Generated product artwork.

The demo catalogue has no photos, so every product gets a clean studio-style SVG drawing
of its kind (earbuds, bottle, sneaker...) in its own colour, plus three extra gallery
views. Admins can upload real photos, which replace the artwork.
"""

from __future__ import annotations

from collections.abc import Callable
from functools import lru_cache


def _clamp(v: float) -> int:
    return max(0, min(255, round(v)))


def _rgb(hex_color: str) -> tuple[int, int, int]:
    h = hex_color.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def mix(hex_color: str, other: str, amount: float) -> str:
    """Blend ``hex_color`` towards ``other`` by ``amount`` (0..1)."""
    a, b = _rgb(hex_color), _rgb(other)
    return "#{:02x}{:02x}{:02x}".format(
        *(_clamp(x + (y - x) * amount) for x, y in zip(a, b, strict=True))
    )


def lighten(c: str, amt: float) -> str:
    """Mix with white."""
    return mix(c, "#ffffff", amt)


def darken(c: str, amt: float) -> str:
    """Mix with black."""
    return mix(c, "#000000", amt)


def is_light(c: str) -> bool:
    """True for light colours (used to pick contrasting detail colours)."""
    r, g, b = _rgb(c)
    return (0.299 * r + 0.587 * g + 0.114 * b) > 170


# Each drawing is centred on (300, 300) in a 600x600 box and may use these fills:
#   url(#b) body gradient, url(#m) brushed metal, url(#s) soft shine.
B, M, S = "url(#b)", "url(#m)", "url(#s)"


def _earbuds(c: str) -> str:
    d = darken(c, 0.35)
    bud = (
        '<g transform="translate({x} 215) rotate({r})">'
        f'<rect x="-22" y="10" width="44" height="120" rx="22" fill="{B}"/>'
        f'<circle r="58" fill="{B}"/><circle r="30" fill="{d}"/>'
        '<ellipse cx="-18" cy="-24" rx="18" ry="9" fill="#fff" opacity=".35"/></g>'
    )
    return (
        f'<rect x="150" y="300" width="300" height="175" rx="86" fill="{B}"/>'
        f'<path d="M156 360 H444" stroke="{d}" stroke-width="5" opacity=".6"/>'
        f'<rect x="165" y="312" width="270" height="34" rx="17" fill="{S}" opacity=".45"/>'
        '<circle cx="300" cy="420" r="6" fill="#34d399"/>'
        + bud.format(x=225, r=-18)
        + bud.format(x=375, r=18)
    )


def _headphones(c: str) -> str:
    d = darken(c, 0.4)
    return (
        f'<path d="M160 330 C150 130 450 130 440 330" fill="none" stroke="{B}" '
        'stroke-width="34" stroke-linecap="round"/>'
        f'<path d="M175 300 C175 175 425 175 425 300" fill="none" stroke="{d}" '
        'stroke-width="10" stroke-linecap="round" opacity=".5"/>'
        f'<rect x="108" y="290" width="104" height="170" rx="48" fill="{B}"/>'
        f'<rect x="388" y="290" width="104" height="170" rx="48" fill="{B}"/>'
        f'<rect x="186" y="305" width="32" height="140" rx="16" fill="{d}"/>'
        f'<rect x="382" y="305" width="32" height="140" rx="16" fill="{d}"/>'
        f'<rect x="122" y="305" width="30" height="80" rx="15" fill="{S}" opacity=".4"/>'
        f'<rect x="402" y="305" width="30" height="80" rx="15" fill="{S}" opacity=".4"/>'
    )


def _speaker(c: str) -> str:
    d = darken(c, 0.45)
    dots = "".join(
        f'<circle cx="{x}" cy="{y}" r="5" fill="{d}"/>'
        for x in range(190, 420, 22)
        for y in range(250, 372, 22)
    )
    return (
        f'<rect x="120" y="215" width="360" height="190" rx="95" fill="{B}"/>'
        f"{dots}"
        f'<rect x="150" y="225" width="300" height="30" rx="15" fill="{S}" opacity=".35"/>'
        f'<rect x="270" y="190" width="60" height="30" rx="10" fill="{d}"/>'
        '<circle cx="300" cy="430" r="0"/>'
        f'<path d="M140 300 q-40 -90 20 -120" fill="none" stroke="{d}" stroke-width="10" '
        'stroke-linecap="round"/>'
    )


def _neckband(c: str) -> str:
    d = darken(c, 0.35)
    return (
        f'<path d="M150 200 C150 470 450 470 450 200" fill="none" stroke="{B}" '
        'stroke-width="40" stroke-linecap="round"/>'
        f'<path d="M150 200 C140 260 120 290 110 320" fill="none" stroke="{d}" stroke-width="5"/>'
        f'<path d="M450 200 C460 260 480 290 490 320" fill="none" stroke="{d}" stroke-width="5"/>'
        f'<circle cx="110" cy="340" r="26" fill="{B}"/><circle cx="490" cy="340" r="26" fill="{B}"/>'
        f'<rect x="135" y="185" width="30" height="60" rx="12" fill="{d}"/>'
        f'<rect x="435" y="185" width="30" height="60" rx="12" fill="{d}"/>'
    )


def _watch(c: str, narrow: bool = False) -> str:
    w = 110 if narrow else 170
    x = 300 - w / 2
    strap_w = w - 40 if not narrow else w - 10
    sx = 300 - strap_w / 2
    accent = lighten(c, 0.5) if not is_light(c) else darken(c, 0.4)
    return (
        f'<rect x="{sx}" y="70" width="{strap_w}" height="170" rx="24" fill="{B}"/>'
        f'<rect x="{sx}" y="360" width="{strap_w}" height="170" rx="24" fill="{B}"/>'
        f'<rect x="{x - 8}" y="182" width="{w + 16}" height="236" rx="{54 if not narrow else 50}" '
        f'fill="{M}"/>'
        f'<rect x="{x}" y="190" width="{w}" height="220" rx="{48 if not narrow else 44}" '
        'fill="#0b0f19"/>'
        f'<text x="300" y="{300 if not narrow else 298}" text-anchor="middle" '
        f'font-family="Arial, sans-serif" font-weight="700" font-size="{48 if not narrow else 30}" '
        'fill="#fff">10:09</text>'
        f'<text x="300" y="{340 if not narrow else 330}" text-anchor="middle" '
        f'font-family="Arial, sans-serif" font-size="{18 if not narrow else 13}" '
        f'fill="{accent}">♥ 72  ·  8,412</text>'
        f'<path d="M{x + 20} 380 h{w - 40}" stroke="#22d3ee" stroke-width="6" '
        'stroke-linecap="round" opacity=".8"/>'
        + (
            ""
            if narrow
            else f'<rect x="{x + w + 6}" y="250" width="16" height="44" rx="6" fill="{M}"/>'
        )
        + f'<path d="M{x + 14} 205 q{w / 3} -10 {w / 2} 30" stroke="#fff" stroke-width="10" '
        'fill="none" opacity=".12"/>'
    )


def _smartwatch(c: str) -> str:
    return _watch(c)


def _band(c: str) -> str:
    return _watch(c, narrow=True)


def _powerbank(c: str) -> str:
    return (
        f'<rect x="185" y="130" width="230" height="350" rx="34" fill="{B}"/>'
        f'<rect x="200" y="145" width="40" height="320" rx="20" fill="{S}" opacity=".35"/>'
        '<rect x="240" y="350" width="120" height="56" rx="12" fill="#0b0f19"/>'
        '<text x="300" y="389" text-anchor="middle" font-family="Arial, sans-serif" '
        'font-weight="700" font-size="30" fill="#4ade80">87%</text>'
        '<rect x="235" y="116" width="40" height="18" rx="5" fill="#111"/>'
        '<rect x="285" y="116" width="40" height="18" rx="5" fill="#111"/>'
        '<rect x="335" y="118" width="26" height="14" rx="7" fill="#111"/>'
        f'<text x="300" y="250" text-anchor="middle" font-family="Arial, sans-serif" '
        f'font-weight="800" font-size="34" fill="{lighten(c, 0.6)}" opacity=".9">20000</text>'
    )


def _charger(c: str) -> str:
    dark = "#1f2937"
    return (
        '<rect x="262" y="120" width="18" height="70" rx="4" fill="url(#m)"/>'
        '<rect x="320" y="120" width="18" height="70" rx="4" fill="url(#m)"/>'
        f'<rect x="195" y="180" width="210" height="250" rx="40" fill="{B}" '
        f'stroke="{darken(c, 0.15)}" stroke-width="2"/>'
        f'<rect x="215" y="195" width="40" height="215" rx="20" fill="{S}" opacity=".5"/>'
        f'<rect x="265" y="250" width="70" height="22" rx="11" fill="{dark}"/>'
        f'<rect x="265" y="290" width="70" height="22" rx="11" fill="{dark}"/>'
        f'<rect x="255" y="330" width="90" height="28" rx="5" fill="{dark}"/>'
        f'<text x="300" y="400" text-anchor="middle" font-family="Arial" font-weight="700" '
        f'font-size="22" fill="{darken(c, 0.5)}">65W GaN</text>'
    )


def _cable(c: str) -> str:
    return (
        f'<path d="M150 420 C80 300 210 180 300 230 C390 280 520 200 450 120" fill="none" '
        f'stroke="{B}" stroke-width="22" stroke-linecap="round"/>'
        f'<path d="M150 420 C80 300 210 180 300 230 C390 280 520 200 450 120" fill="none" '
        'stroke="#fff" stroke-width="4" stroke-dasharray="6 10" opacity=".35"/>'
        '<g transform="translate(150 430) rotate(20)"><rect x="-22" y="-10" width="44" '
        'height="70" rx="10" fill="#27272a"/><rect x="-14" y="56" width="28" height="34" rx="8" '
        'fill="url(#m)"/></g>'
        '<g transform="translate(455 110) rotate(210)"><rect x="-22" y="-10" width="44" '
        'height="70" rx="10" fill="#27272a"/><rect x="-14" y="56" width="28" height="34" rx="8" '
        'fill="url(#m)"/></g>'
    )


def _phonecase(c: str) -> str:
    return (
        '<rect x="205" y="90" width="190" height="400" rx="40" fill="#1e293b"/>'
        f'<rect x="200" y="85" width="200" height="410" rx="44" fill="{c}" opacity=".35" '
        f'stroke="{darken(c, 0.2)}" stroke-width="6"/>'
        '<rect x="222" y="108" width="100" height="100" rx="26" fill="#0f172a"/>'
        '<circle cx="248" cy="134" r="18" fill="#334155" stroke="#94a3b8" stroke-width="4"/>'
        '<circle cx="248" cy="182" r="18" fill="#334155" stroke="#94a3b8" stroke-width="4"/>'
        '<circle cx="296" cy="158" r="18" fill="#334155" stroke="#94a3b8" stroke-width="4"/>'
        '<circle cx="300" cy="320" r="70" fill="none" stroke="#e2e8f0" stroke-width="8" '
        'opacity=".7"/>'
        '<rect x="215" y="100" width="24" height="380" rx="12" fill="#fff" opacity=".18"/>'
    )


def _keyboard(c: str) -> str:
    keys = []
    for row in range(5):
        for col in range(14):
            x = 108 + col * 28.5
            y = 236 + row * 30
            if row == 4 and 4 <= col <= 9:
                continue
            keys.append(f'<rect x="{x}" y="{y}" width="24" height="25" rx="5" fill="#e5e7eb"/>')
    return (
        f'<rect x="88" y="214" width="424" height="182" rx="22" fill="{B}"/>'
        + "".join(keys)
        + '<rect x="222" y="356" width="166" height="25" rx="5" fill="#e5e7eb"/>'
        + '<rect x="108" y="236" width="24" height="25" rx="5" fill="#f97316"/>'
        + '<rect x="88" y="214" width="424" height="16" rx="8" fill="#fff" opacity=".12"/>'
    )


def _mouse(c: str) -> str:
    d = darken(c, 0.35)
    return (
        f'<path d="M300 120 C400 120 410 230 410 320 C410 430 360 490 300 490 C240 490 190 430 '
        f'190 320 C190 230 200 120 300 120 Z" fill="{B}"/>'
        f'<path d="M300 125 V260" stroke="{d}" stroke-width="5"/>'
        f'<path d="M195 260 Q300 285 405 260" stroke="{d}" stroke-width="5" fill="none"/>'
        '<rect x="288" y="160" width="24" height="54" rx="12" fill="#111827"/>'
        f'<path d="M225 170 C230 140 260 130 280 130" stroke="#fff" stroke-width="12" '
        'fill="none" stroke-linecap="round" opacity=".3"/>'
    )


def _laptopstand(c: str) -> str:
    return (
        '<polygon points="140,420 470,250 490,280 165,450" fill="url(#m)"/>'
        '<rect x="185" y="380" width="22" height="110" rx="6" fill="url(#m)" '
        'transform="rotate(-12 196 435)"/>'
        '<rect x="410" y="285" width="22" height="200" rx="6" fill="url(#m)" '
        'transform="rotate(10 421 385)"/>'
        '<polygon points="150,405 465,240 470,250 152,416" fill="#1f2937"/>'
        '<polygon points="380,110 470,240 464,245 372,118" fill="#1f2937"/>'
        '<polygon points="383,122 462,236 300,110" fill="#334155"/>'
    )


def _bottle(c: str) -> str:
    return (
        '<rect x="252" y="70" width="96" height="60" rx="14" fill="#27272a"/>'
        '<rect x="262" y="58" width="76" height="20" rx="8" fill="#3f3f46"/>'
        '<path d="M262 130 H338 L350 165 H250 Z" fill="url(#m)"/>'
        f'<rect x="222" y="160" width="156" height="345" rx="46" fill="{B}"/>'
        f'<rect x="222" y="300" width="156" height="60" fill="{darken(c, 0.25)}" opacity=".5"/>'
        '<text x="300" y="338" text-anchor="middle" font-family="Arial" font-weight="800" '
        'font-size="22" fill="#fff" opacity=".85" letter-spacing="2">HYDRO</text>'
        f'<rect x="238" y="175" width="26" height="310" rx="13" fill="{S}" opacity=".45"/>'
    )


def _mug(c: str) -> str:
    d = darken(c, 0.3)
    return (
        f'<path d="M395 255 C470 255 470 395 395 395" fill="none" stroke="{d}" '
        'stroke-width="28"/>'
        f'<rect x="180" y="210" width="230" height="250" rx="34" fill="{B}"/>'
        f'<ellipse cx="295" cy="214" rx="113" ry="18" fill="{darken(c, 0.5)}"/>'
        f'<rect x="196" y="235" width="26" height="200" rx="13" fill="{S}" opacity=".35"/>'
        f'<path d="M180 330 Q295 360 410 330" stroke="{lighten(c, 0.4)}" stroke-width="6" '
        'fill="none" opacity=".6"/>'
        '<path d="M260 180 q-20 -30 0 -60 M300 180 q-20 -30 0 -60 M340 180 q-20 -30 0 -60" '
        'stroke="#94a3b8" stroke-width="6" fill="none" stroke-linecap="round" opacity=".6"/>'
    )


def _kettle(c: str) -> str:
    return (
        '<ellipse cx="300" cy="470" rx="150" ry="22" fill="#27272a"/>'
        '<path d="M195 455 L215 200 H385 L405 455 Z" fill="url(#m)"/>'
        '<path d="M215 200 L170 150 L185 140 L235 200 Z" fill="url(#m)"/>'
        '<path d="M385 215 C470 215 470 400 395 420" stroke="#27272a" stroke-width="30" '
        'fill="none"/>'
        '<rect x="250" y="180" width="100" height="26" rx="10" fill="#27272a"/>'
        '<rect x="285" y="166" width="30" height="18" rx="6" fill="#27272a"/>'
        '<rect x="225" y="215" width="26" height="230" rx="13" fill="#fff" opacity=".4"/>'
        '<circle cx="300" cy="420" r="8" fill="#ef4444"/>'
    )


def _pan(c: str) -> str:
    return (
        '<rect x="400" y="282" width="170" height="36" rx="18" fill="#3f2a1d" '
        'transform="rotate(-8 400 300)"/>'
        f'<circle cx="270" cy="300" r="165" fill="{B}"/>'
        f'<circle cx="270" cy="300" r="140" fill="{darken(c, 0.25)}"/>'
        f'<circle cx="270" cy="300" r="140" fill="{S}" opacity=".08"/>'
        '<path d="M175 220 A120 120 0 0 1 260 170" stroke="#fff" stroke-width="10" fill="none" '
        'opacity=".15" stroke-linecap="round"/>'
    )


def _lamp(c: str) -> str:
    return (
        '<path d="M330 175 L470 440 H210 Z" fill="#fde68a" opacity=".35"/>'
        '<ellipse cx="200" cy="480" rx="110" ry="24" fill="#27272a"/>'
        '<circle cx="200" cy="470" r="34" fill="#d4d4d8" opacity=".5"/>'
        '<path d="M200 460 L250 200 L360 160" stroke="#3f3f46" stroke-width="16" fill="none" '
        'stroke-linecap="round" stroke-linejoin="round"/>'
        '<circle cx="250" cy="200" r="14" fill="#52525b"/>'
        f'<rect x="300" y="132" width="150" height="50" rx="22" fill="{B}" '
        'transform="rotate(20 375 157)"/>'
    )


def _backpack(c: str) -> str:
    d = darken(c, 0.35)
    return (
        f'<path d="M260 105 C260 70 340 70 340 105" stroke="{d}" stroke-width="16" fill="none"/>'
        f'<rect x="170" y="100" width="260" height="400" rx="70" fill="{B}"/>'
        f'<rect x="205" y="300" width="190" height="170" rx="36" fill="{darken(c, 0.15)}"/>'
        f'<path d="M215 320 H385" stroke="{lighten(c, 0.35)}" stroke-width="5" '
        'stroke-dasharray="10 6"/>'
        f'<path d="M200 170 Q300 140 400 170" stroke="{lighten(c, 0.35)}" stroke-width="5" '
        'fill="none" stroke-dasharray="10 6"/>'
        '<rect x="285" y="330" width="30" height="12" rx="6" fill="#e5e7eb"/>'
        f'<rect x="188" y="125" width="30" height="340" rx="15" fill="{S}" opacity=".25"/>'
    )


def _tshirt(c: str) -> str:
    d = darken(c, 0.25)
    return (
        '<path d="M225 110 L160 130 L90 200 L150 270 L190 240 L190 490 H410 L410 240 L450 270 '
        'L510 200 L440 130 L375 110 C360 150 240 150 225 110 Z" fill="url(#b)"/>'
        f'<path d="M225 110 C240 150 360 150 375 110" stroke="{d}" stroke-width="10" '
        'fill="none"/>'
        f'<path d="M190 240 V490 M410 240 V490" stroke="{d}" stroke-width="3" opacity=".4"/>'
        '<path d="M215 170 L215 470" stroke="#fff" stroke-width="18" opacity=".1"/>'
    )


def _sneaker(c: str) -> str:
    d = darken(c, 0.3)
    return (
        '<path d="M95 410 C95 440 120 455 160 455 H470 C505 455 520 435 515 410 Z" '
        'fill="#f8fafc" stroke="#cbd5e1" stroke-width="4"/>'
        '<path d="M95 410 C95 330 140 290 200 270 L290 200 C320 220 345 240 370 300 C420 320 '
        '490 340 515 410 Z" fill="url(#b)"/>'
        f'<path d="M290 200 L250 160 C270 150 300 160 315 180" fill="{d}"/>'
        '<path d="M255 240 L300 225 M265 262 L315 248 M280 285 L330 272" stroke="#fff" '
        'stroke-width="7" stroke-linecap="round"/>'
        f'<path d="M180 380 Q300 300 470 390" stroke="{lighten(c, 0.6)}" stroke-width="12" '
        'fill="none" stroke-linecap="round"/>'
        '<path d="M100 440 H510" stroke="#94a3b8" stroke-width="3" stroke-dasharray="12 8"/>'
    )


def _sunglasses(c: str) -> str:
    return (
        f'<path d="M110 250 H490" stroke="{B}" stroke-width="18" stroke-linecap="round"/>'
        f'<path d="M120 255 C120 380 270 380 275 260 Z" fill="{B}"/>'
        f'<path d="M325 260 C330 380 480 380 480 255 Z" fill="{B}"/>'
        '<path d="M140 270 C150 330 210 345 240 330" stroke="#fff" stroke-width="10" '
        'fill="none" opacity=".25" stroke-linecap="round"/>'
        '<path d="M345 270 C355 330 415 345 445 330" stroke="#fff" stroke-width="10" '
        'fill="none" opacity=".25" stroke-linecap="round"/>'
        f'<path d="M275 262 Q300 240 325 262" stroke="{B}" stroke-width="12" fill="none"/>'
    )


def _yogamat(c: str) -> str:
    d = darken(c, 0.3)
    return (
        f'<rect x="150" y="230" width="330" height="160" rx="20" fill="{B}" '
        'transform="skewX(-8)"/>'
        f'<circle cx="430" cy="310" r="80" fill="{c}"/>'
        f'<circle cx="430" cy="310" r="58" fill="none" stroke="{d}" stroke-width="7"/>'
        f'<circle cx="430" cy="310" r="36" fill="none" stroke="{d}" stroke-width="7"/>'
        f'<circle cx="430" cy="310" r="14" fill="{d}"/>'
        '<path d="M190 245 C280 200 360 200 430 230" stroke="#3f3f46" stroke-width="8" '
        'fill="none"/>'
    )


def _dumbbell(c: str) -> str:
    plate = (
        '<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="12" fill="url(#b)"/>'
        '<rect x="{x}" y="{y}" width="8" height="{h}" rx="4" fill="#fff" opacity=".15"/>'
    )
    out = '<rect x="120" y="285" width="360" height="30" rx="8" fill="url(#m)"/>'
    for x, y, w, h in [
        (140, 200, 40, 200),
        (185, 225, 32, 150),
        (420, 200, 40, 200),
        (383, 225, 32, 150),
    ]:
        out += plate.format(x=x, y=y, w=w, h=h)
    return out + '<rect x="240" y="280" width="120" height="40" rx="10" fill="#52525b"/>'


def _shaker(c: str) -> str:
    return (
        '<rect x="225" y="95" width="150" height="70" rx="20" fill="#1f2937"/>'
        '<rect x="255" y="70" width="50" height="34" rx="10" fill="#374151"/>'
        f'<path d="M215 165 H385 L365 495 H235 Z" fill="{c}" opacity=".85"/>'
        '<path d="M215 165 H385 L365 495 H235 Z" fill="url(#s)" opacity=".2"/>'
        '<path d="M228 260 H372 M232 330 H368 M236 400 H364" stroke="#fff" stroke-width="3" '
        'opacity=".6"/>'
        '<rect x="232" y="180" width="18" height="300" rx="9" fill="#fff" opacity=".3"/>'
    )


def _trimmer(c: str) -> str:
    return (
        '<rect x="245" y="110" width="110" height="60" rx="8" fill="url(#m)"/>'
        + "".join(
            f'<rect x="{x}" y="96" width="6" height="22" fill="#a1a1aa"/>'
            for x in range(250, 352, 12)
        )
        + f'<rect x="235" y="160" width="130" height="330" rx="60" fill="{B}"/>'
        '<circle cx="300" cy="300" r="20" fill="#0ea5e9" opacity=".8"/>'
        '<rect x="252" y="180" width="22" height="280" rx="11" fill="#fff" opacity=".15"/>'
    )


def _perfume(c: str) -> str:
    return (
        '<rect x="262" y="90" width="76" height="80" rx="12" fill="#18181b"/>'
        '<rect x="282" y="160" width="36" height="34" fill="url(#m)"/>'
        f'<rect x="185" y="190" width="230" height="290" rx="30" fill="{c}" opacity=".35"/>'
        f'<rect x="197" y="250" width="206" height="218" rx="22" fill="{B}"/>'
        '<rect x="235" y="300" width="130" height="80" rx="6" fill="#fef3c7" opacity=".9"/>'
        f'<text x="300" y="350" text-anchor="middle" font-family="Georgia, serif" '
        f'font-size="26" fill="{darken(c, 0.4)}">OJAS</text>'
        '<rect x="200" y="200" width="20" height="270" rx="10" fill="#fff" opacity=".35"/>'
    )


def _notebook(c: str) -> str:
    return (
        '<rect x="200" y="100" width="250" height="380" rx="14" fill="#e7e5e4"/>'
        f'<rect x="180" y="90" width="250" height="390" rx="14" fill="{B}"/>'
        '<rect x="380" y="90" width="14" height="390" fill="#1c1917" opacity=".7"/>'
        '<path d="M300 480 V540 L312 528 L324 540 V480" fill="#dc2626"/>'
        f'<rect x="230" y="180" width="110" height="60" rx="6" fill="{lighten(c, 0.8)}" '
        'opacity=".85"/>'
        f'<text x="285" y="218" text-anchor="middle" font-family="Georgia, serif" '
        f'font-size="20" fill="{darken(c, 0.4)}">kagaz</text>'
    )


def _pens(c: str) -> str:
    hues = [c, "#2563eb", "#16a34a", "#f59e0b", "#7c3aed", "#0891b2"]
    out = ""
    for i, h in enumerate(hues):
        x = 170 + i * 48
        out += (
            f'<g transform="rotate({-8 + i * 3} {x + 14} 300)">'
            f'<rect x="{x}" y="110" width="28" height="330" rx="12" fill="{h}"/>'
            f'<rect x="{x}" y="320" width="28" height="70" fill="#111827" opacity=".35"/>'
            f'<path d="M{x} 440 L{x + 14} 485 L{x + 28} 440 Z" fill="#d4d4d8"/>'
            f'<rect x="{x + 4}" y="120" width="6" height="190" rx="3" fill="#fff" opacity=".35"/>'
            "</g>"
        )
    return out


def _box(c: str) -> str:
    return (
        f'<polygon points="300,130 470,210 300,290 130,210" fill="{lighten(c, 0.3)}"/>'
        f'<polygon points="130,210 300,290 300,480 130,400" fill="{c}"/>'
        f'<polygon points="470,210 300,290 300,480 470,400" fill="{darken(c, 0.25)}"/>'
    )


DRAWINGS: dict[str, Callable[[str], str]] = {
    "earbuds": _earbuds, "headphones": _headphones, "speaker": _speaker,
    "neckband": _neckband, "smartwatch": _smartwatch, "band": _band,
    "powerbank": _powerbank, "charger": _charger, "cable": _cable, "phonecase": _phonecase,
    "keyboard": _keyboard, "mouse": _mouse, "laptopstand": _laptopstand, "bottle": _bottle,
    "mug": _mug, "kettle": _kettle, "pan": _pan, "lamp": _lamp, "backpack": _backpack,
    "tshirt": _tshirt, "sneaker": _sneaker, "sunglasses": _sunglasses, "yogamat": _yogamat,
    "dumbbell": _dumbbell, "shaker": _shaker, "trimmer": _trimmer, "perfume": _perfume,
    "notebook": _notebook, "pens": _pens, "box": _box,
}  # fmt: skip

# Gallery views: (background tint, transform applied to the drawing, extra decoration)
_VIEWS = [
    (0.93, "", ""),
    (0.88, "rotate(-10 300 300) translate(10 10) scale(.92)", ""),
    (0.96, "translate(-150 -150) scale(1.5)", ""),
    (0.90, "translate(60 70) scale(.8)", "box"),
]


@lru_cache(maxsize=512)
def product_svg(kind: str, color: str, view: int = 0, label: str = "") -> str:
    """Render a product drawing as a standalone SVG document."""
    draw = DRAWINGS.get(kind, _box)
    tint, transform, extra = _VIEWS[view % len(_VIEWS)]
    bg_center = mix(color, "#ffffff", min(0.985, tint + 0.05))
    bg_edge = mix(color, "#ffffff", tint - 0.04)
    body_light = lighten(color, 0.28)
    body_dark = darken(color, 0.28)
    decoration = ""
    if extra == "box":
        decoration = (
            '<rect x="60" y="90" width="230" height="300" rx="10" fill="#fff" '
            'stroke="#e5e7eb" stroke-width="3"/>'
            f'<rect x="60" y="90" width="230" height="56" rx="10" fill="{color}"/>'
            f'<text x="175" y="128" text-anchor="middle" font-family="Arial" font-weight="800" '
            f'font-size="22" fill="{"#111" if is_light(color) else "#fff"}">'
            f"{(label or 'NORTHCART')[:14].upper()}</text>"
            '<rect x="85" y="175" width="180" height="10" rx="5" fill="#e5e7eb"/>'
            '<rect x="85" y="200" width="140" height="10" rx="5" fill="#e5e7eb"/>'
            '<rect x="85" y="225" width="160" height="10" rx="5" fill="#e5e7eb"/>'
        )
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 600 600" width="600" height="600">'
        "<defs>"
        f'<radialGradient id="bg" cx="50%" cy="42%" r="70%"><stop offset="0" stop-color="{bg_center}"/>'
        f'<stop offset="1" stop-color="{bg_edge}"/></radialGradient>'
        f'<linearGradient id="b" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="{body_light}"/>'
        f'<stop offset=".55" stop-color="{color}"/><stop offset="1" stop-color="{body_dark}"/>'
        "</linearGradient>"
        '<linearGradient id="m" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="#f4f4f5"/>'
        '<stop offset=".5" stop-color="#a1a1aa"/><stop offset="1" stop-color="#e4e4e7"/>'
        "</linearGradient>"
        '<linearGradient id="s" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#fff"/>'
        '<stop offset="1" stop-color="#fff" stop-opacity="0"/></linearGradient>'
        '<filter id="sh" x="-20%" y="-20%" width="140%" height="140%">'
        '<feGaussianBlur stdDeviation="14"/></filter>'
        "</defs>"
        '<rect width="600" height="600" fill="url(#bg)"/>'
        f"{decoration}"
        f'<ellipse cx="300" cy="520" rx="190" ry="26" fill="#0f172a" opacity=".16" filter="url(#sh)"/>'
        f'<g transform="{transform}">{draw(color)}</g>'
        "</svg>"
    )
