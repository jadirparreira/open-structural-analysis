"""Angular and elevation dimensions in the same paper renderer as linear ones."""
import math
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QPainterPath, QPen, QPolygonF

SPECIAL_DIMENSION_DEFAULTS = {
    'angular_dimension_decimal_places': 1,
    'angular_dimension_text_height_mm': 3.,
    'angular_dimension_terminator_height_mm': 3.,
    'angular_dimension_min_radius_mm': 8.,
    'angular_dimension_text_color': '#000000',
    'angular_dimension_line_color': '#ff0000',
    'level_dimension_decimal_places': 3,
    'level_dimension_text_height_mm': 3.,
    'level_dimension_symbol_height_mm': 3.,
    'level_dimension_line_length_mm': 15.,
    'level_dimension_reference_m': 0.,
    'level_dimension_text_color': '#000000',
    'level_dimension_line_color': '#ff0000',
}


def elevation(ws, view_index, point):
    """Invert the orthographic basis on the view plane, including its origin."""
    view = ws._sheet_views[view_index]
    projection = view.get('projection', {})
    plane = projection.get('plane')
    if plane == 'custom':
        try:
            origin = tuple(float(v) for v in projection['coordinate'][0])
        except (KeyError, TypeError, ValueError, IndexError):
            return None
    else:
        origin = (0., 0., float(projection.get('coordinate', 0.))) if plane == 'XY' else (0., 0., 0.)
    base = ws._project_world_point(view, origin)
    probe = ws._project_world_point(view, (origin[0], origin[1], origin[2]+1))
    if base is None or probe is None:
        return None
    return origin[2]+(probe[0]-base[0])*(point[0]-base[0])+(probe[1]-base[1])*(point[1]-base[1])


def angular_geometry(dimension):
    vertex = dimension['vertex']
    vectors = [(dimension[key][0]-vertex[0], dimension[key][1]-vertex[1]) for key in ('start', 'end')]
    if any(math.hypot(*v) < 1e-9 for v in vectors):
        return None
    a, b = [math.atan2(y, x) for x, y in vectors]
    span = (b-a) % math.tau
    if min(span, math.tau-span) < 1e-8:
        return None
    placement = math.atan2(dimension['offset'][1], dimension['offset'][0])
    if (placement-a) % math.tau > span:
        a, span = b, math.tau-span
    return a, span


def make_dimension(ws, view_index, points, cursor):
    kind = ws._dimension_type
    anchor = points[0]
    if kind == 'angular':
        if len(points) != 3:
            return None
        mark = dict(kind=kind, vertex=anchor, start=points[1], end=points[2],
                    offset=(cursor[0]-anchor[0], cursor[1]-anchor[1]))
        return mark if angular_geometry(mark) else None
    if not points or elevation(ws, view_index, anchor) is None:
        return None
    return dict(kind='level', start=anchor, end=anchor,
                offset=(cursor[0]-anchor[0], cursor[1]-anchor[1]))


def dimension_layout(ws, view_index, dimension, font):
    kind = dimension['kind']; prefix = kind+'_dimension_'
    def setting(name):
        return ws._project_settings.get(prefix+name, SPECIAL_DIMENSION_DEFAULTS[prefix+name])
    scale = ws._sheet_pixels_per_mm
    factor = ws._view_draw_data[view_index][4]
    path = QPainterPath(); fills = []
    font = QFont(font); font.setPixelSize(max(1, round(float(setting('text_height_mm'))*scale)))
    metrics = QFontMetricsF(font)
    decimals = max(0, min(8, int(setting('decimal_places'))))
    if kind == 'angular':
        geometry = angular_geometry(dimension)
        if geometry is None:
            return None
        a, span = geometry
        center = ws._screen_point(view_index, dimension['vertex'])
        if center is None:
            return None
        radius = max(float(setting('min_radius_mm'))*scale, math.hypot(*dimension['offset'])*factor)
        circle = QRectF(center.x()-radius, center.y()-radius, radius*2, radius*2)
        path.arcMoveTo(circle, math.degrees(a)); path.arcTo(circle, math.degrees(a), math.degrees(span))
        def radial(angle, distance):
            return center+QPointF(math.cos(angle), -math.sin(angle))*distance
        for key in ('start', 'end'):
            endpoint = ws._screen_point(view_index, dimension[key])
            angle = math.atan2(center.y()-endpoint.y(), endpoint.x()-center.x())
            path.moveTo(endpoint); path.lineTo(radial(angle, radius+2*scale))
        arrow = min(float(setting('terminator_height_mm'))*scale, radius*.4)
        for angle, sign in ((a, 1), (a+span, -1)):
            tip = radial(angle, radius)
            tangent = QPointF(-math.sin(angle), -math.cos(angle))*sign
            normal = QPointF(math.cos(angle), -math.sin(angle))
            fills.append(QPolygonF([tip, tip+tangent*arrow+normal*arrow*.25,
                                   tip+tangent*arrow-normal*arrow*.25]))
        value = math.degrees(span)
        text = f'{value:.{decimals}f}'.replace('.', ',')+'°'
        bisector = a+span/2
        clearance = (abs(math.cos(bisector))*metrics.horizontalAdvance(text)/2
                     + abs(math.sin(bisector))*metrics.height()/2 + 1.5*scale)
        text_center = radial(bisector, radius+clearance)
    else:
        anchor = ws._screen_point(view_index, dimension['start'])
        if anchor is None:
            return None
        value = elevation(ws, view_index, dimension['start'])
        if value is None:
            return None
        value -= float(setting('reference_m'))
        if abs(value) < .5*10**(-decimals):
            value = 0.
        text = f'{value:+.{decimals}f}'.replace('.', ',')+' m'
        size = float(setting('symbol_height_mm'))*scale
        path.moveTo(anchor+QPointF(-size, 0)); path.lineTo(anchor+QPointF(size, 0))
        fills.append(QPolygonF([anchor, anchor+QPointF(-size/2, -size), anchor+QPointF(size/2, -size)]))
        elbow = anchor+QPointF(dimension['offset'][0]*factor, -dimension['offset'][1]*factor)
        direction = 1 if dimension['offset'][0] >= 0 else -1
        length = max(float(setting('line_length_mm'))*scale, metrics.horizontalAdvance(text)+2*scale)
        path.moveTo(anchor); path.lineTo(elbow); path.lineTo(elbow+QPointF(direction*length, 0))
        text_center = elbow+QPointF(direction*length/2, -metrics.height()/2-scale)
    rect = QRectF(text_center.x()-metrics.horizontalAdvance(text)/2,
                  text_center.y()-metrics.height()/2, metrics.horizontalAdvance(text), metrics.height())
    bounds = path.boundingRect().united(rect)
    for polygon in fills:
        bounds = bounds.united(polygon.boundingRect())
    return dict(path=path, fills=fills, text=text, font=font, text_rect=rect,
                bounds=bounds.adjusted(-8, -8, 8, 8))


def draw_dimension(ws, painter, view_index, dimension, dimension_index=None):
    layout = dimension_layout(ws, view_index, dimension, painter.font())
    if layout is None:
        return None
    prefix = dimension['kind']+'_dimension_'
    painter.save()
    pen = QPen(QColor(ws._project_settings.get(prefix+'line_color', '#ff0000')), 1.)
    pen.setCosmetic(True); painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush); painter.drawPath(layout['path'])
    painter.setBrush(pen.color())
    for polygon in layout['fills']:
        painter.drawPolygon(polygon)
    painter.setFont(layout['font'])
    painter.setPen(QColor(ws._project_settings.get(prefix+'text_color', '#000000')))
    painter.drawText(layout['text_rect'], Qt.AlignmentFlag.AlignCenter, layout['text'])
    if dimension_index is not None:
        key = view_index, dimension_index
        ws._dimension_text_hit_rects[key] = layout['text_rect'].adjusted(-6, -6, 6, 6)
        ws._dimension_bounds[key] = layout['bounds']
        if ws._selected_dimension == key:
            painter.setPen(QPen(QColor('#0969da'), 1.))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(layout['text_rect'].adjusted(-3, -3, 3, 3))
            painter.setBrush(QColor('white'))
            for name in (('start', 'end', 'vertex') if dimension['kind'] == 'angular' else ('start',)):
                point = ws._screen_point(view_index, dimension[name])
                painter.drawEllipse(point, 4, 4)
                ws._dimension_endpoint_hit_rects[view_index, dimension_index, name] = QRectF(point.x()-8, point.y()-8, 16, 16)
    painter.restore()
    return layout['bounds']
