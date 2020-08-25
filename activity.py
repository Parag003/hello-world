# Copyright 2009 Simon Schampijer
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA  02110-1301  USA

"""HelloWorld Activity: A case study for developing an activity."""

import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk

from gettext import gettext as _

from sugar3.activity import activity
from sugar3.graphics.toolbarbox import ToolbarBox
from sugar3.activity.widgets import StopButton
from sugar3.activity.widgets import ActivityToolbarButton


import six
import re
import math
import logging
import os

from six.moves.configparser import ConfigParser

import gi
gi.require_version('Rsvg', '2.0')
gi.require_version('Gtk', '3.0')
from gi.repository import GLib
from gi.repository import GObject
from gi.repository import Gtk
from gi.repository import Gdk
from gi.repository import GdkPixbuf
from gi.repository import Rsvg
import cairo

from sugar3.graphics import style
from sugar3.graphics.xocolor import XoColor
from sugar3.util import LRU

_BADGE_SIZE = 0.45


class _SVGLoader(object):

    def __init__(self):
        self._cache = LRU(100)

    def load(self, file_name, entities, cache):
        if file_name in self._cache:
            icon = self._cache[file_name]
        else:
            icon_file = open(file_name, 'r')
            icon = icon_file.read()
            icon_file.close()

            if cache:
                self._cache[file_name] = icon

        for entity, value in list(entities.items()):
            if isinstance(value, six.string_types):
                xml = '<!ENTITY %s "%s">' % (entity, value)
                icon = re.sub('<!ENTITY %s .*>' % entity, xml, icon)
            else:
                logging.error(
                    'Icon %s, entity %s is invalid.', file_name, entity)

        return Rsvg.Handle.new_from_data(icon.encode('utf-8'))


class _IconInfo(object):

    def __init__(self):
        self.file_name = None
        self.attach_x = 0
        self.attach_y = 0


class _BadgeInfo(object):

    def __init__(self):
        self.attach_x = 0
        self.attach_y = 0
        self.size = 0
        self.icon_padding = 0


class _IconBuffer(object):

    _surface_cache = LRU(100)
    _loader = _SVGLoader()

    def __init__(self):
        self.icon_name = None
        self.icon_size = None
        self.file_name = None
        self.fill_color = None
        self.background_color = None
        self.stroke_color = None
        self.badge_name = None
        self.width = None
        self.height = None
        self.cache = False
        self.scale = 1.0
        self.pixbuf = None

    def _get_cache_key(self, sensitive):
        if self.background_color is None:
            color = None
        else:
            color = (self.background_color.red, self.background_color.green,
                     self.background_color.blue)

        return (self.icon_name, self.file_name, self.pixbuf, self.fill_color,
                self.stroke_color, self.badge_name, self.width, self.height,
                color, sensitive)

    def _load_svg(self, file_name):
        entities = {}
        if self.fill_color:
            entities['fill_color'] = self.fill_color
        if self.stroke_color:
            entities['stroke_color'] = self.stroke_color

        return self._loader.load(file_name, entities, self.cache)

    def _get_attach_points(self, info, size_request):
        has_attach_points_, attach_points = info.get_attach_points()
        attach_x = attach_y = 0
        if attach_points:
            # this works only for Gtk < 3.14
            # https://developer.gnome.org/gtk3/stable/GtkIconTheme.html
            # #gtk-icon-info-get-attach-points
            attach_x = float(attach_points[0].x) / size_request
            attach_y = float(attach_points[0].y) / size_request
        elif info.get_filename():
            # try read from the .icon file
            icon_filename = info.get_filename().replace('.svg', '.icon')
            if icon_filename != info.get_filename() and \
                    os.path.exists(icon_filename):

                try:
                    with open(icon_filename) as config_file:
                        cp = ConfigParser()
                        cp.readfp(config_file)
                        attach_points_str = cp.get('Icon Data', 'AttachPoints')
                        attach_points = attach_points_str.split(',')
                        attach_x = float(attach_points[0].strip()) / 1000
                        attach_y = float(attach_points[1].strip()) / 1000
                except Exception as e:
                    logging.exception('Exception reading icon info: %s', e)

        return attach_x, attach_y

    def _get_icon_info(self, file_name, icon_name):
        icon_info = _IconInfo()

        if file_name:
            icon_info.file_name = file_name
        elif icon_name:
            theme = Gtk.IconTheme.get_default()

            size = 50
            if self.width is not None:
                size = self.width

            info = theme.lookup_icon(icon_name, int(size), 0)
            if info:
                attach_x, attach_y = self._get_attach_points(info, size)

                icon_info.file_name = info.get_filename()
                icon_info.attach_x = attach_x
                icon_info.attach_y = attach_y

                del info
            else:
                logging.warning('No icon with the name %s was found in the '
                                'theme.', icon_name)

        return icon_info

    def _draw_badge(self, context, size, sensitive, widget):
        theme = Gtk.IconTheme.get_default()
        badge_info = theme.lookup_icon(self.badge_name, int(size), 0)
        if badge_info:
            badge_file_name = badge_info.get_filename()
            if badge_file_name.endswith('.svg'):
                handle = self._loader.load(badge_file_name, {}, self.cache)

                icon_width = handle.props.width
                icon_height = handle.props.height

                pixbuf = handle.get_pixbuf()
            else:
                pixbuf = GdkPixbuf.Pixbuf.new_from_file(badge_file_name)

                icon_width = pixbuf.get_width()
                icon_height = pixbuf.get_height()

            context.scale(float(size) / icon_width,
                          float(size) / icon_height)

            if not sensitive:
                pixbuf = self._get_insensitive_pixbuf(pixbuf, widget)
            Gdk.cairo_set_source_pixbuf(context, pixbuf, 0, 0)
            context.paint()

    def _get_size(self, icon_width, icon_height, padding):
        if self.width is not None and self.height is not None:
            width = self.width + padding
            height = self.height + padding
        else:
            width = icon_width + padding
            height = icon_height + padding

        return width, height

    def _get_badge_info(self, icon_info, icon_width, icon_height):
        info = _BadgeInfo()
        if self.badge_name is None:
            return info

        info.size = int(_BADGE_SIZE * icon_width)
        info.attach_x = int(icon_info.attach_x * icon_width - info.size / 2)
        info.attach_y = int(icon_info.attach_y * icon_height - info.size / 2)

        if info.attach_x < 0 or info.attach_y < 0:
            info.icon_padding = max(-info.attach_x, -info.attach_y)
        elif info.attach_x + info.size > icon_width or \
                info.attach_y + info.size > icon_height:
            x_padding = info.attach_x + info.size - icon_width
            y_padding = info.attach_y + info.size - icon_height
            info.icon_padding = max(x_padding, y_padding)

        return info

    def _get_xo_color(self):
        if self.stroke_color and self.fill_color:
            return XoColor('%s,%s' % (self.stroke_color, self.fill_color))
        else:
            return None

    def _set_xo_color(self, xo_color):
        if xo_color:
            self.stroke_color = xo_color.get_stroke_color()
            self.fill_color = xo_color.get_fill_color()
        else:
            self.stroke_color = None
            self.fill_color = None

    def _get_insensitive_pixbuf(self, pixbuf, widget):
        if not (widget and widget.get_style()):
            return pixbuf

        icon_source = Gtk.IconSource()
        # Special size meaning "don't touch"
        icon_source.set_size(-1)
        icon_source.set_pixbuf(pixbuf)
        icon_source.set_state(Gtk.StateType.INSENSITIVE)
        icon_source.set_direction_wildcarded(False)
        icon_source.set_size_wildcarded(False)

        widget_style = widget.get_style()
        pixbuf = widget_style.render_icon(
            icon_source, widget.get_direction(),
            Gtk.StateType.INSENSITIVE, -1, widget,
            'sugar-icon')

        return pixbuf

    def get_surface(self, sensitive=True, widget=None):
        cache_key = self._get_cache_key(sensitive)
        if cache_key in self._surface_cache:
            return self._surface_cache[cache_key]

        if self.pixbuf:
            # We alredy have the pixbuf for this icon.
            pixbuf = self.pixbuf
            icon_width = pixbuf.get_width()
            icon_height = pixbuf.get_height()
            icon_info = self._get_icon_info(self.file_name, self.icon_name)
            is_svg = False
        else:
            # We run two attempts at finding the icon. First, we try the icon
            # requested by the user. If that fails, we fall back on
            # document-generic. If that doesn't work out, bail.
            icon_width = None
            for (file_name, icon_name) in ((self.file_name, self.icon_name),
                                           (None, 'document-generic')):
                icon_info = self._get_icon_info(file_name, icon_name)
                if icon_info.file_name is None:
                    return None

                is_svg = icon_info.file_name.endswith('.svg')

                if is_svg:
                    try:
                        handle = self._load_svg(icon_info.file_name)
                        icon_width = handle.props.width
                        icon_height = handle.props.height
                        break
                    except IOError:
                        pass
                else:
                    try:
                        path = icon_info.file_name
                        pixbuf = GdkPixbuf.Pixbuf.new_from_file(path)
                        icon_width = pixbuf.get_width()
                        icon_height = pixbuf.get_height()
                        break
                    except GLib.GError:
                        pass

        if icon_width is None:
            # Neither attempt found an icon for us to use
            return None

        badge_info = self._get_badge_info(icon_info, icon_width, icon_height)

        padding = badge_info.icon_padding
        width, height = self._get_size(icon_width, icon_height, padding)
        if self.background_color is None:
            surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, int(width),
                                         int(height))
            context = cairo.Context(surface)
        else:
            surface = cairo.ImageSurface(cairo.FORMAT_RGB24, int(width),
                                         int(height))
            context = cairo.Context(surface)
            context.set_source_color(self.background_color)
            context.paint()

        context.scale(float(width) / (icon_width + padding * 2),
                      float(height) / (icon_height + padding * 2))
        context.save()

        context.translate(padding, padding)
        if is_svg:
            if sensitive:
                handle.render_cairo(context)
            else:
                pixbuf = handle.get_pixbuf()
                pixbuf = self._get_insensitive_pixbuf(pixbuf, widget)

                Gdk.cairo_set_source_pixbuf(context, pixbuf, 0, 0)
                context.paint()
        else:
            if not sensitive:
                pixbuf = self._get_insensitive_pixbuf(pixbuf, widget)
            Gdk.cairo_set_source_pixbuf(context, pixbuf, 0, 0)
            context.paint()

        if self.badge_name:
            context.restore()
            context.translate(badge_info.attach_x, badge_info.attach_y)
            self._draw_badge(context, badge_info.size, sensitive, widget)

        self._surface_cache[cache_key] = surface

        return surface

    xo_color = property(_get_xo_color, _set_xo_color)


class Icon(Gtk.Image):
    '''
    The most basic Sugar icon class.  Displays the icon given.

    You must set either the `file_name`, `file` or `icon_name` properties,
    otherwise, no icon will be visible.

    You should set the `pixel_size`, using constants the `*_ICON_SIZE`
    constants from :any:`sugar3.graphics.style`.

    You should set the color (either via `xo_color` or `fill_color` and
    `stroke_color`), otherwise the default black and white fill and stroke
    will be used.

    Keyword Args:
        file_name (str): a path to the SVG icon file
        file (object): same behaviour as file_name, but for
            :class:`sugar3.util.TempFilePath` type objects
        icon_name (str): a name of an icon in the theme to display.  The
            icons in the theme include those in the sugar-artwork project
            and icons in the activity's '/icons' directory
        pixel_size (int): size of the icon, in pixels.  Best to use the
            constants from :class:`sugar3.graphics.style`, as those constants
            are scaled based on the user's preferences
        xo_color (sugar3.graphics.xocolor.XoColor): color to display icon,
            a shortcut that just sets the fill_color and stroke_color
        fill_color (str): a string, like '#FFFFFF', that will serve as the
            fill color for the icon
        stroke_color (str): a string, like '#282828', that will serve as the
            stroke color for the icon
        icon_size: deprecated since 0.102.0, use pixel_size instead
        badge_name (str): the icon_name for a badge icon,
            see :any:`set_badge_name`
        alpha (float): transparency of the icon, defaults to 1.0
    '''

    __gtype_name__ = 'HelloIcon'

    _MENU_SIZES = (Gtk.IconSize.MENU, Gtk.IconSize.DND,
                   Gtk.IconSize.SMALL_TOOLBAR, Gtk.IconSize.BUTTON)

    def __init__(self, **kwargs):
        self._buffer = _IconBuffer()
        # HACK: need to keep a reference to the path so it doesn't get garbage
        # collected while it's still used if it's a sugar3.util.TempFilePath.
        # See #1175
        self._file = None
        self._alpha = 1.0
        self._scale = 1.0

        if 'icon_size' in kwargs:
            logging.warning("icon_size is deprecated. Use pixel_size instead.")

        GObject.GObject.__init__(self, **kwargs)

    def get_file(self):
        return self._file

    def set_file(self, file_name):
        self._file = file_name
        self._buffer.file_name = file_name

    file = GObject.Property(type=object, setter=set_file, getter=get_file)

    def get_pixbuf(self):
        '''
        Returns the :class:`GdkPixbuf.Pixbuf` for the icon, if one has been
        loaded yet.  If the icon has been drawn (:any:`do_draw`), the icon
        will be loaded.

        The pixbuf only contains the SVG icon that has been loaded and
        recoloured.  It does not contain the badge.
        '''
        return self._buffer.pixbuf

    def set_pixbuf(self, pixbuf):
        '''
        Set the pixbuf.  This will force the icon to be rendered with the
        given pixbuf.  The icon will still be centered, badge added, etc.

        Args:
            pixbuf (GdkPixbuf.Pixbuf): pixbuf to set
        '''
        self._buffer.pixbuf = pixbuf

    pixbuf = GObject.Property(type=object, setter=set_pixbuf,
                              getter=get_pixbuf)
    '''
    icon.props.pixbuf -> see :any:`get_pixbuf` and :any:`set_pixbuf`
    '''

    def _sync_image_properties(self):
        if self._buffer.icon_name != self.props.icon_name:
            self._buffer.icon_name = self.props.icon_name

        if self._buffer.file_name != self.props.file:
            self._buffer.file_name = self.props.file

        pixel_size = None
        if self.props.pixel_size == -1:
            if self.props.icon_size in self._MENU_SIZES:
                pixel_size = style.SMALL_ICON_SIZE
            else:
                pixel_size = style.STANDARD_ICON_SIZE
        else:
            pixel_size = self.props.pixel_size

        width = height = pixel_size

        if self._buffer.width != width or self._buffer.height != height:
            self._buffer.width = width
            self._buffer.height = height

    def _icon_size_changed_cb(self, image, pspec):
        self._buffer.icon_size = self.props.pixel_size

    def _icon_name_changed_cb(self, image, pspec):
        self._buffer.icon_name = self.props.icon_name

    def _file_changed_cb(self, image, pspec):
        self._buffer.file_name = self.props.file

    def do_get_preferred_height(self):
        '''Gtk widget implementation method'''
        self._sync_image_properties()
        surface = self._buffer.get_surface()
        if surface:
            height = surface.get_height()
        elif self._buffer.height:
            height = self._buffer.height
        else:
            height = 0
        return (height, height)

    def do_get_preferred_width(self):
        '''Gtk widget implementation method'''
        self._sync_image_properties()
        surface = self._buffer.get_surface()
        if surface:
            width = surface.get_width()
        elif self._buffer.width:
            width = self._buffer.width
        else:
            width = 0
        return (width, width)

    def do_draw(self, cr):
        '''Gtk widget implementation method'''
        self._sync_image_properties()
        sensitive = (self.is_sensitive())
        surface = self._buffer.get_surface(sensitive, self)
        if surface is None:
            return

        xpad, ypad = self.get_padding()
        xalign, yalign = self.get_alignment()
        requisition = self.get_child_requisition()
        if self.get_direction() != Gtk.TextDirection.LTR:
            xalign = 1.0 - xalign

        allocation = self.get_allocation()
        x = math.floor(xpad +
                       (allocation.width - requisition.width) * xalign)
        y = math.floor(ypad +
                       (allocation.height - requisition.height) * yalign)

        if self._scale != 1.0:
            cr.scale(self._scale, self._scale)

            margin = self._buffer.width * (1 - self._scale) / 2
            x, y = x + margin, y + margin

            x = x / self._scale
            y = y / self._scale

        cr.set_source_surface(surface, x, y)

        if self._alpha == 1.0:
            cr.paint()
        else:
            cr.paint_with_alpha(self._alpha)

    def set_xo_color(self, value):
        '''
        Set the colors used to display the icon

        Args:
            value (sugar3.graphics.xocolor.XoColor): new XoColor to use
        '''
        if self._buffer.xo_color != value:
            self._buffer.xo_color = value
            self.queue_draw()

    xo_color = GObject.Property(
        type=object, getter=None, setter=set_xo_color)
    '''
    icon.props.xo_color -> see :any:`set_xo_color`, note there is no getter
    '''

    def set_fill_color(self, value):
        '''
        Set the color used to fill the icon

        Args:
            value (str): SVG color string, like '#FFFFFF'
        '''
        if self._buffer.fill_color != value:
            self._buffer.fill_color = value
            self.queue_draw()

    def get_fill_color(self):
        '''
        Get the color used to fill the icon

        Returns:
            str, SVG color string, like '#FFFFFF'
        '''
        return self._buffer.fill_color

    fill_color = GObject.Property(
        type=object, getter=get_fill_color, setter=set_fill_color)
    '''
    icon.props.fill_color -> see :any:`get_fill_color`
        and :any:`set_fill_color`
    '''

    def set_stroke_color(self, value):
        '''
        Set the color used to paint the icon stroke

        Args:
            value (str): SVG color string, like '#282828'
        '''
        if self._buffer.stroke_color != value:
            self._buffer.stroke_color = value
            self.queue_draw()

    def get_stroke_color(self):
        '''
        Get the color used to paint the icon stroke

        Returns:
            str, SVG color string, like '#282828'
        '''
        return self._buffer.stroke_color

    stroke_color = GObject.Property(
        type=object, getter=get_stroke_color, setter=set_stroke_color)
    '''
    icon.props.stroke_color -> see :any:`get_stroke_color`
        and :any:`set_stroke_color`
    '''

    def set_badge_name(self, value):
        '''
        See the Badge Icons section at the top of the file.

        Args:
            value (str): the icon name for the badge
        '''
        if self._buffer.badge_name != value:
            self._buffer.badge_name = value
            self.queue_resize()

    def get_badge_name(self):
        '''
        Get the badge name, as set by :any:`set_badge_name`

        Returns:
            str, badge icon name
        '''
        return self._buffer.badge_name

    badge_name = GObject.Property(
        type=str, getter=get_badge_name, setter=set_badge_name)
    '''
    icon.props.badge_name -> see :any:`get_badge_name`
        and :any:`set_badge_name`
    '''

    def get_badge_size(self):
        '''
        Returns:
            int, size of badge icon, in pixels
        '''
        return int(_BADGE_SIZE * self.props.pixel_size)

    def set_alpha(self, value):
        '''
        Set the transparency for the icon.  Defaults to 1.0, which is
        fully visible icon.

        Args:
            value (float): alpha value from 0.0 to 1.0
        '''
        if self._alpha != value:
            self._alpha = value
            self.queue_draw()

    alpha = GObject.Property(
        type=float, setter=set_alpha)
    '''
    icon.props.alpha -> see :any:`set_alpha`, note no getter
    '''

    def set_scale(self, value):
        '''
        Scales the icon, with the transformation origin at the top left
        corner.  Note that this only scales the resulting drawing, so
        at large scales the icon will appear pixilated.

        Args:
            value (float): new scaling factor
        '''
        if self._scale != value:
            self._scale = value
            self.queue_draw()

    scale = GObject.Property(
        type=float, setter=set_scale)
    '''
    icon.props.scale -> see :any:`set_scale`, note no getter
    '''


class HelloWorldActivity(activity.Activity):
    """HelloWorldActivity class as specified in activity.info"""

    def __init__(self, handle):
        """Set up the HelloWorld activity."""
        activity.Activity.__init__(self, handle)

        self.max_participants = 1

        toolbar_box = ToolbarBox()

        activity_button = ActivityToolbarButton(self)
        toolbar_box.toolbar.insert(activity_button, 0)
        activity_button.show()

        separator = Gtk.SeparatorToolItem()
        separator.props.draw = False
        separator.set_expand(True)
        toolbar_box.toolbar.insert(separator, -1)
        separator.show()

        stop_button = StopButton(self)
        toolbar_box.toolbar.insert(stop_button, -1)
        stop_button.show()

        self.set_toolbar_box(toolbar_box)
        toolbar_box.show()

        icon = Icon(file='wrap.svg',
                    stroke_color='#aaa', fill_color='#fff', pixel_size=600)
        self.set_canvas(icon)
        icon.show()
