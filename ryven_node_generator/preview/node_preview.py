"""
Lightweight Ryven node preview widget — Pure Dark theme.
Renders a single node with ports, input widgets, and main widgets.
"""

import re
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QGraphicsScene, QGraphicsView,
    QGraphicsItem, QGraphicsDropShadowEffect,
)
from PySide6.QtCore import Qt, QRectF, QPointF
from PySide6.QtGui import (
    QPainter, QPen, QBrush, QColor, QFont, QFontMetricsF, QPainterPath,
)

# ── Pure Dark theme constants (from Ryven FlowTheme_PureDark) ──────────
FLOW_BG      = '#1E242A'
GRID_COLOR   = '#2a3038'
GRID_SPACING = 50
NODE_BG      = '#0C1116'
SHADOW_COLOR = '#101010'
TITLE_COLOR  = '#ffffff'
PORT_LABEL_C = '#53585c'
PIN_PEN_C    = '#ffffff'

HEADER_PAD = (4, 4, 4, 4)   # left, top, right, bottom
BODY_PAD   = 8
BODY_RAD   = 3

PIN_R      = 5.5
PIN_TOTAL  = 17
ROW_H      = 22
MIN_W      = 150
COL_GAP    = 24

# input‑widget drawing
IW_BG      = '#252526'
IW_BORDER  = '#3e3e3e'
IW_TEXT    = '#cccccc'
IW_H       = 20
IW_WIDTHS  = {
    'int_spinbox': 70, 'float_spinbox': 70,
    'line_edit': 70, 'combo_box': 80, 'slider': 120,
}

# main‑widget intrinsic sizes  (width, height) — width 0 means "fill"
MW_DEFAULTS = {
    'button':         (0,   28),
    'text_display':   (180, 100),
    'image_display':  (220, 160),
    'matrix_display': (180, 100),
    'custom':         (140,  70),
}


# ── helpers to parse args strings ──────────────────────────────────────

def _arg_str(s, key, default=''):
    if not s:
        return default
    for pat in (rf"{key}\s*=\s*'([^']*)'",
                rf'{key}\s*=\s*"([^"]*)"',
                rf'{key}\s*=\s*([^,\s\)]+)'):
        m = re.search(pat, s)
        if m:
            return m.group(1)
    return default


def _first_item(s):
    if not s:
        return 'A'
    m = re.search(r"items\s*=\s*\[([^\]]*)\]", s)
    if m:
        parts = re.findall(r"'([^']*)'|\"([^\"]*)\"", m.group(1))
        if parts:
            return parts[0][0] or parts[0][1]
    return 'A'


def _dim(s, dw, dh):
    w, h = dw, dh
    m = re.search(r'width\s*=\s*(\d+)', s or '')
    if m: w = int(m.group(1))
    m = re.search(r'height\s*=\s*(\d+)', s or '')
    if m: h = int(m.group(1))
    m = re.search(r'max_height\s*=\s*(\d+)', s or '')
    if m: h = min(h, int(m.group(1)))
    return w, h


def _slider_ratio(args):
    init = float(_arg_str(args, 'init', '0.5'))
    m = re.search(r'range\s*=\s*\(([^)]+)\)', args or '')
    if m:
        parts = m.group(1).split(',')
        if len(parts) >= 2:
            lo, hi = float(parts[0]), float(parts[1])
            if hi > lo:
                return max(0.0, min(1.0, (init - lo) / (hi - lo)))
    return 0.5


# ── Scene ──────────────────────────────────────────────────────────────

class _PreviewScene(QGraphicsScene):

    def __init__(self):
        super().__init__()
        self.setBackgroundBrush(QBrush(QColor(FLOW_BG)))

    def drawBackground(self, painter, rect):
        super().drawBackground(painter, rect)
        vis = rect.intersected(self.sceneRect())
        if vis.isEmpty():
            return
        gs = GRID_SPACING
        if (vis.width() / gs) * (vis.height() / gs) > 3000:
            return
        pen = QPen(QColor(GRID_COLOR))
        pen.setWidth(2)
        painter.setPen(pen)
        x = int(vis.left() / gs) * gs
        while x <= vis.right():
            y = int(vis.top() / gs) * gs
            while y <= vis.bottom():
                painter.drawPoint(QPointF(x, y))
                y += gs
            x += gs


# ── Node graphics item ─────────────────────────────────────────────────

class _NodeGfx(QGraphicsItem):

    def __init__(self):
        super().__init__()
        self._d = None
        self._rect = QRectF(-70, -30, 140, 60)
        self._hdr_h = 20
        self._in_w = 0
        self._out_w = 0
        self._in_rows = []      # per-input row height
        self._mw_wh = (0, 0)    # (w, h) of main widget area

    # fonts
    @staticmethod
    def _f(family="Segoe UI", size=10, bold=False):
        f = QFont()
        f.setFamily(family)
        ps = max(1, int(size))
        f.setPointSize(ps)
        if bold:
            f.setBold(True)
        return f

    _title_font = None
    _port_font  = None
    _iw_font    = None

    def _ensure_fonts(self):
        if self._title_font is None:
            _NodeGfx._title_font = self._f('Segoe UI', 11)
            _NodeGfx._port_font  = self._f('Segoe UI', 10)
            _NodeGfx._iw_font    = self._f('Segoe UI', 7)

    # data setter
    def set_node_data(self, data):
        self.prepareGeometryChange()
        self._d = data
        self._ensure_fonts()
        self._calc()
        self.update()

    # ── layout calculation ──────────────────────────────────────────

    def _calc(self):
        d = self._d
        if not d:
            return

        tfm = QFontMetricsF(self._title_font)
        pfm = QFontMetricsF(self._port_font)

        title = d.get('title', 'Node')
        tw = tfm.horizontalAdvance(title + '___')
        th = tfm.height() * 0.7

        hp, bp = HEADER_PAD, BODY_PAD
        hdr_h = th + hp[1] + hp[3]
        hdr_w = tw + hp[0] + hp[2]

        inputs  = d.get('inputs', [])
        outputs = d.get('outputs', [])
        has_mw  = d.get('has_main_widget', False)
        mw_pos  = d.get('main_widget_pos', 'below ports')
        mw_tpl  = d.get('main_widget_template', '')
        mw_args = d.get('main_widget_args', '')

        # --- input column --------------------------------------------------
        max_in_w = 0
        in_rows = []
        for inp in inputs:
            lbl_w = pfm.horizontalAdvance(inp.get('label', ''))
            rh = ROW_H
            extra = 0
            wi = inp.get('widget')
            if wi and wi.get('type', 'None') != 'None' and inp.get('type') == 'data':
                ww = IW_WIDTHS.get(wi['type'], 70)
                if wi.get('pos') == 'besides':
                    extra = 6 + ww
                else:
                    rh += IW_H + 2
                    max_in_w = max(max_in_w, PIN_TOTAL + 4 + ww)
            max_in_w = max(max_in_w, lbl_w + extra)
            in_rows.append(rh)

        self._in_rows = in_rows
        in_col = (PIN_TOTAL + 4 + max_in_w) if inputs else 0

        # --- output column -------------------------------------------------
        max_out_lbl = max((pfm.horizontalAdvance(p.get('label', ''))
                           for p in outputs), default=0)
        out_col = (max_out_lbl + 4 + PIN_TOTAL) if outputs else 0

        in_total_h  = sum(in_rows) if in_rows else 0
        out_total_h = len(outputs) * ROW_H
        ports_h     = max(in_total_h, out_total_h, 0)

        # --- main widget ---------------------------------------------------
        mw_w = mw_h = 0
        if has_mw and mw_tpl and mw_tpl != 'None':
            dw, dh = MW_DEFAULTS.get(mw_tpl, (140, 70))
            if mw_tpl == 'image_display':
                mw_w, mw_h = _dim(mw_args, dw, dh)
            elif mw_tpl in ('text_display', 'matrix_display'):
                _, mw_h = _dim(mw_args, 180, dh)
                mw_w = dw
            elif mw_tpl == 'button':
                mw_w, mw_h = 0, dh     # width filled later
            else:
                mw_w, mw_h = dw, dh

        if has_mw and mw_pos == 'between ports' and mw_w > 0:
            content_w = in_col + 12 + mw_w + 12 + out_col
            body_h = max(ports_h, mw_h) + 2 * bp
        else:
            content_w = (in_col + COL_GAP + out_col) if (inputs or outputs) else 0
            body_h = ports_h + (mw_h + bp if has_mw and mw_h else 0) + 2 * bp

        w = max(hdr_w, content_w + 2 * bp, MIN_W)
        if has_mw and mw_pos == 'below ports' and mw_w > 0:
            w = max(w, mw_w + 2 * bp + 20)
        h = hdr_h + body_h

        # for button: fill width
        if has_mw and mw_tpl == 'button' and mw_w == 0:
            mw_w = max(w - 2 * bp - 20, 80)
            w = max(w, mw_w + 2 * bp + 20)

        self._hdr_h  = hdr_h
        self._in_w   = in_col
        self._out_w  = out_col
        self._mw_wh  = (mw_w, mw_h)
        self._rect   = QRectF(-w / 2, -h / 2, w, h)

    def boundingRect(self):
        return self._rect.adjusted(-25, -25, 25, 25)

    # ── paint ───────────────────────────────────────────────────────

    def paint(self, painter, option, widget=None):
        d = self._d
        if not d:
            return

        painter.setRenderHint(QPainter.Antialiasing)

        color   = d.get('color', '#ffffff') or '#ffffff'
        title   = d.get('title', 'Node')
        inputs  = d.get('inputs', [])
        outputs = d.get('outputs', [])
        has_mw  = d.get('has_main_widget', False)
        mw_pos  = d.get('main_widget_pos', 'below ports')
        mw_tpl  = d.get('main_widget_template', '')
        mw_args = d.get('main_widget_args', '')

        R   = self._rect
        hh  = self._hdr_h
        bp  = BODY_PAD
        hp  = HEADER_PAD

        # ── background ────────────────────────────────────────────
        c = QColor(color)
        body = QRectF(R.left(), R.top() + hh, R.width(), R.height() - hh)
        painter.setBrush(QColor(NODE_BG))
        painter.setPen(Qt.NoPen)
        painter.drawRoundedRect(body, BODY_RAD, BODY_RAD)
        pen = QPen(c); pen.setWidthF(2.3)
        painter.setPen(pen)
        painter.drawLine(QPointF(R.left(), R.top() + hh),
                         QPointF(R.right(), R.top() + hh))

        # ── title ─────────────────────────────────────────────────
        painter.setPen(QPen(QColor(TITLE_COLOR)))
        painter.setFont(self._title_font)
        tr = QRectF(R.left() + hp[0], R.top() + hp[1],
                    R.width() - hp[0] - hp[2], hh - hp[1] - hp[3])
        painter.drawText(tr, Qt.AlignLeft | Qt.AlignVCenter, title)

        # ── input ports + widgets ─────────────────────────────────
        body_top = R.top() + hh + bp
        pfm = QFontMetricsF(self._port_font)
        y_off = 0.0

        for i, inp in enumerate(inputs):
            rh = self._in_rows[i] if i < len(self._in_rows) else ROW_H
            y = body_top + y_off + ROW_H / 2

            # pin
            pcx = R.left() + bp + PIN_TOTAL / 2
            self._pin(painter, pcx, y, inp.get('type', 'data'), color)

            # label
            painter.setPen(QPen(QColor(PORT_LABEL_C)))
            painter.setFont(self._port_font)
            lbl = inp.get('label', '')
            lbl_x = R.left() + bp + PIN_TOTAL + 4
            painter.drawText(QRectF(lbl_x, y - ROW_H / 2, 200, ROW_H),
                             Qt.AlignLeft | Qt.AlignVCenter, lbl)

            # input widget
            wi = inp.get('widget')
            if wi and wi.get('type', 'None') != 'None' and inp.get('type') == 'data':
                wt = wi['type']
                ww = IW_WIDTHS.get(wt, 70)
                wa = wi.get('args', '')
                if wi.get('pos') == 'besides':
                    wx = lbl_x + pfm.horizontalAdvance(lbl) + 6
                    wr = QRectF(wx, y - IW_H / 2, ww, IW_H)
                else:
                    wr = QRectF(R.left() + bp + PIN_TOTAL, y + ROW_H / 2 + 1,
                                ww, IW_H)
                self._iw(painter, wr, wt, wa)

            y_off += rh

        # ── output ports ──────────────────────────────────────────
        for i, out in enumerate(outputs):
            y = body_top + i * ROW_H + ROW_H / 2
            pcx = R.right() - bp - PIN_TOTAL / 2
            self._pin(painter, pcx, y, out.get('type', 'data'), color)
            painter.setPen(QPen(QColor(PORT_LABEL_C)))
            painter.setFont(self._port_font)
            painter.drawText(
                QRectF(R.right() - bp - PIN_TOTAL - 4 - 200,
                       y - ROW_H / 2, 200, ROW_H),
                Qt.AlignRight | Qt.AlignVCenter, out.get('label', ''))

        # ── main widget ───────────────────────────────────────────
        if has_mw and mw_tpl and mw_tpl != 'None':
            mw_w, mw_h = self._mw_wh
            if mw_w <= 0 or mw_h <= 0:
                return
            in_h  = sum(self._in_rows) if self._in_rows else 0
            out_h = len(outputs) * ROW_H
            ph    = max(in_h, out_h, 0)

            if mw_pos == 'below ports':
                mw_top = body_top + ph + bp
                mx = R.center().x() - mw_w / 2
                mr = QRectF(mx, mw_top, mw_w, mw_h)
            else:
                mx = R.left() + bp + self._in_w + 12
                mr = QRectF(mx, body_top, mw_w, max(ph, mw_h))
            self._mw(painter, mr, mw_tpl, mw_args)

    # ── drawing primitives ─────────────────────────────────────────

    @staticmethod
    def _pin(painter, cx, cy, type_, color):
        if type_ == 'exec':
            painter.setBrush(QBrush(QColor('white')))
            painter.setPen(Qt.NoPen)
        else:
            painter.setBrush(Qt.NoBrush)
            p = QPen(QColor(PIN_PEN_C)); p.setWidthF(1.1)
            painter.setPen(p)
        painter.drawEllipse(QPointF(cx, cy), PIN_R, PIN_R)

    def _iw(self, painter, r, wtype, args):
        """Draw an input widget (spinbox / line_edit / combo / slider)."""
        painter.setBrush(QColor(IW_BG))
        painter.setPen(QPen(QColor(IW_BORDER)))
        painter.drawRoundedRect(r, 2, 2)

        painter.setFont(self._iw_font)
        painter.setPen(QPen(QColor(IW_TEXT)))

        if wtype in ('int_spinbox', 'float_spinbox'):
            v = _arg_str(args, 'init', '1' if wtype == 'int_spinbox' else '0.50')
            painter.drawText(r.adjusted(4, 0, -14, 0),
                             Qt.AlignLeft | Qt.AlignVCenter, v)
            self._spinbox_arrows(painter, r)

        elif wtype == 'line_edit':
            v = _arg_str(args, 'init', 'default')
            painter.drawText(r.adjusted(4, 0, -4, 0),
                             Qt.AlignLeft | Qt.AlignVCenter, v)

        elif wtype == 'combo_box':
            painter.drawText(r.adjusted(4, 0, -14, 0),
                             Qt.AlignLeft | Qt.AlignVCenter,
                             _first_item(args))
            self._combo_arrow(painter, r)

        elif wtype == 'slider':
            self._slider(painter, r, args)

    # ---- micro‑widgets ------------------------------------------------

    @staticmethod
    def _spinbox_arrows(p, r):
        ax = r.right() - 12
        my = r.center().y()
        p.setPen(QPen(QColor('#888888')))
        p.setBrush(QColor('#888888'))
        t = QPainterPath()
        t.moveTo(ax, my - 2); t.lineTo(ax + 4, my - 6); t.lineTo(ax + 8, my - 2)
        t.closeSubpath(); p.drawPath(t)
        b = QPainterPath()
        b.moveTo(ax, my + 2); b.lineTo(ax + 4, my + 6); b.lineTo(ax + 8, my + 2)
        b.closeSubpath(); p.drawPath(b)

    @staticmethod
    def _combo_arrow(p, r):
        ax, ay = r.right() - 12, r.center().y() - 3
        p.setPen(QPen(QColor('#888888')))
        p.setBrush(QColor('#888888'))
        t = QPainterPath()
        t.moveTo(ax, ay); t.lineTo(ax + 8, ay); t.lineTo(ax + 4, ay + 6)
        t.closeSubpath(); p.drawPath(t)

    def _slider(self, p, r, args):
        v = _arg_str(args, 'init', '0.50')
        # value box
        vw = 35
        vr = QRectF(r.left(), r.top(), vw, r.height())
        p.setBrush(QColor('#1a1a2e'))
        p.setPen(QPen(QColor(IW_BORDER)))
        p.drawRect(vr)
        p.setPen(QPen(QColor(IW_TEXT)))
        p.setFont(self._iw_font)
        p.drawText(vr, Qt.AlignCenter, v)
        # track
        tx = r.left() + vw + 4
        tw = r.width() - vw - 8
        ty = r.center().y()
        p.setPen(QPen(QColor('#555555'), 2))
        p.drawLine(QPointF(tx, ty), QPointF(tx + tw, ty))
        # handle
        ratio = _slider_ratio(args)
        p.setBrush(QColor("#5f7d93"))
        p.setPen(Qt.NoPen)
        p.drawEllipse(QPointF(tx + tw * ratio, ty), 4, 4)

    # ---- main widget ---------------------------------------------------

    def _mw(self, p, r, tpl, args):
        if tpl == 'button':
            txt = _arg_str(args, 'button_text', 'Apply')
            p.setBrush(QColor('#333333'))
            p.setPen(QPen(QColor('#555555')))
            p.drawRoundedRect(r, 3, 3)
            p.setPen(QPen(QColor('#cccccc')))
            p.setFont(self._f('Segoe UI', 9))
            p.drawText(r, Qt.AlignCenter, txt)

        elif tpl in ('text_display', 'matrix_display'):
            ttl = _arg_str(args, 'title', 'Text' if tpl == 'text_display' else 'Matrix')
            th = 18
            p.setPen(QPen(QColor('#aaaaaa')))
            p.setFont(self._f('Segoe UI', 7))
            p.drawText(QRectF(r.left(), r.top(), r.width(), th),
                       Qt.AlignLeft | Qt.AlignVCenter, f'  {ttl}')
            tr = QRectF(r.left(), r.top() + th, r.width(), r.height() - th)
            p.setBrush(QColor('#1a1a2e'))
            p.setPen(QPen(QColor(IW_BORDER)))
            p.drawRoundedRect(tr, 2, 2)
            p.setPen(QPen(QColor('#555555')))
            p.setFont(self._f('Consolas', 7))
            placeholder = ('No Data' if tpl == 'text_display'
                           else '[[0.0, 0.0],\n [0.0, 0.0]]')
            p.drawText(tr.adjusted(4, 4, -4, -4),
                       Qt.AlignTop | Qt.AlignLeft, placeholder)

        elif tpl == 'image_display':
            p.setBrush(QColor('#1f1f1f'))
            p.setPen(QPen(QColor('#666666')))
            p.drawRect(r)
            p.setPen(QPen(QColor('#aaaaaa')))
            p.setFont(self._f('Segoe UI', 9))
            placeholder = _arg_str(args, 'placeholder', 'No Image')
            p.drawText(r, Qt.AlignCenter, placeholder)

        else:
            p.setBrush(QColor(40, 40, 40, 80))
            pen = QPen(QColor('#555555')); pen.setStyle(Qt.DashLine)
            p.setPen(pen)
            p.drawRoundedRect(r, 4, 4)
            p.setPen(QPen(QColor('#666666')))
            p.setFont(self._f('Segoe UI', 9))
            p.drawText(r, Qt.AlignCenter, f'[{tpl}]')


# ── Public widget ──────────────────────────────────────────────────────

class NodePreviewWidget(QWidget):
    """Drop‑in preview widget. Call update_preview(node_data_dict) to refresh."""

    def __init__(self):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)

        self.scene = _PreviewScene()
        self.scene.setSceneRect(-500, -500, 1000, 1000)

        self.view = QGraphicsView(self.scene)
        self.view.setRenderHint(QPainter.Antialiasing)
        self.view.setDragMode(QGraphicsView.ScrollHandDrag)
        self.view.setViewportUpdateMode(QGraphicsView.FullViewportUpdate)
        self.view.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.view.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        self._node = _NodeGfx()
        shadow = QGraphicsDropShadowEffect()
        shadow.setXOffset(12); shadow.setYOffset(12)
        shadow.setBlurRadius(20)
        shadow.setColor(QColor(SHADOW_COLOR))
        self._node.setGraphicsEffect(shadow)
        self.scene.addItem(self._node)

        lay.addWidget(self.view)

    def update_preview(self, node_data):
        self._node.set_node_data(node_data)
        self.view.centerOn(self._node)
