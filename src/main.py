import sys
import os
import threading
import time
from datetime import datetime
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QLabel, 
                             QSystemTrayIcon, QMenu, QAction, QVBoxLayout, 
                             QHBoxLayout, QLineEdit, QPushButton, QSpinBox, 
                             QFileDialog, QMessageBox, QGroupBox, QCheckBox,
                             QRadioButton, QButtonGroup, QComboBox, QInputDialog)
from PyQt5.QtCore import Qt, QRect, QPoint, pyqtSignal, QTimer, QThread
from PyQt5.QtGui import QPainter, QColor, QPen, QPixmap, QIcon
import keyboard
import json
import logging

# Setup logging for debugging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class HotkeyThread(QThread):
    """Run keyboard hooks in a separate thread to prevent blocking the UI"""
    hotkey_triggered = pyqtSignal()
    
    def __init__(self, hotkey):
        super().__init__()
        self.hotkey = hotkey
        self.is_running = False
        self.daemon = True
    
    def run(self):
        try:
            self.is_running = True
            logger.info(f"Hotkey thread started for: {self.hotkey}")
            keyboard.add_hotkey(self.hotkey, self._on_hotkey)
            # Keep thread alive
            while self.is_running:
                time.sleep(0.1)
        except Exception as e:
            logger.error(f"Error in hotkey thread: {e}")
        finally:
            logger.info("Hotkey thread ended")
    
    def _on_hotkey(self):
        """Emit signal when hotkey is pressed"""
        self.hotkey_triggered.emit()
    
    def stop(self):
        """Stop the hotkey thread"""
        self.is_running = False
        try:
            keyboard.unhook_all()
        except Exception as e:
            logger.error(f"Error stopping hotkey thread: {e}")
        self.wait()


class CaptureOverlay(QWidget):
    capture_signal = pyqtSignal(QRect)
    close_signal = pyqtSignal()
    update_ui_dimensions = pyqtSignal(int, int)  # width, height
    
    def __init__(self, settings):
        super().__init__()
        self.settings = settings
        
        # Make overlay truly block everything behind it
        self.setWindowFlags(
            Qt.WindowStaysOnTopHint | 
            Qt.FramelessWindowHint | 
            Qt.Tool |
            Qt.BypassWindowManagerHint  # Bypass window manager for full control
        )
        
        # Don't use translucent background - we'll paint everything ourselves
        self.setWindowState(Qt.WindowFullScreen)
        
        # Grab all mouse and keyboard input
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.grabKeyboard()
        self.grabMouse()
        
        # Get all screens and create combined geometry
        self.screens = QApplication.screens()
        self.setup_full_desktop_geometry()
        
        # Calculate capture rectangle
        width = settings.get('portrait_width', 1080)
        height = settings.get('portrait_height', 1920)
        
        # Find screen with mouse cursor
        from PyQt5.QtGui import QCursor
        mouse_pos = QCursor.pos()
        screen = QApplication.screenAt(mouse_pos)
        if screen is None:
            screen = QApplication.primaryScreen()
        
        screen_geom = screen.geometry()
        screen_width = screen_geom.width()
        screen_height = screen_geom.height()
        screen_left = screen_geom.left()
        screen_top = screen_geom.top()
        
        logger.info(f"Active screen: left={screen_left}, top={screen_top}, w={screen_width}, h={screen_height}")
        logger.info(f"Full desktop offset: {self.full_desktop_offset.x()}, {self.full_desktop_offset.y()}")
        logger.info(f"Capture size: w={width}, h={height}")
        
        # Try to use last captured region if it's still valid
        last_rect = self.get_valid_last_region(width, height)
        
        if last_rect is not None:
            self.capture_rect = last_rect
            logger.info(f"Using last captured region: x={last_rect.x()}, y={last_rect.y()}, w={last_rect.width()}, h={last_rect.height()}")
        else:
            # Center horizontally within active screen
            x = screen_left + (screen_width - width) // 2
            
            # Center vertically within active screen
            y = screen_top + (screen_height - height) // 2
            
            # Clamp to ensure rectangle stays within screen bounds
            x = max(screen_left, min(x, screen_left + screen_width - width))
            y = max(screen_top, min(y, screen_top + screen_height - height))
            
            self.capture_rect = QRect(int(x), int(y), int(width), int(height))
            logger.info(f"Capture rect (centered): x={int(x)}, y={int(y)}, w={int(width)}, h={int(height)}")
        
        self.dragging = False
        self.drag_offset = QPoint()
        self.resizing = False
        self.resize_edge = None  # Which edge is being resized
        self.resize_min_size = 100  # Minimum resize dimension
        
        # Capture all screens
        self.capture_screens()
        
    def get_valid_last_region(self, width, height):
        """
        Check if the last captured region is still valid for current screen setup.
        Uses separate storage for portrait (9:16) and landscape (16:9) modes.
        Returns a QRect adjusted for current screen geometry, or None if invalid.
        """
        try:
            # Use the ratio_mode from settings (not inferred from dimensions)
            ratio_mode = self.settings.get('ratio_mode', '9:16')
            
            # Get the appropriate last region key
            region_key = f'last_capture_rect_{ratio_mode}'
            last_rect_data = self.settings.get(region_key)
            
            if not last_rect_data:
                return None
            
            last_x = last_rect_data.get('x')
            last_y = last_rect_data.get('y')
            last_w = last_rect_data.get('width')
            last_h = last_rect_data.get('height')
            
            # Check if dimensions match current settings
            if last_w != width or last_h != height:
                return None
            
            last_rect = QRect(last_x, last_y, last_w, last_h)
            
            # Check if the last region is still valid (overlaps with any screen)
            for screen in self.screens:
                screen_geom = screen.geometry()
                if last_rect.intersects(screen_geom):
                    # Clamp to ensure it stays within full desktop bounds
                    valid_rect = self.clamp_rect_to_desktop(last_rect)
                    return valid_rect
            
            return None
            
        except Exception as e:
            logger.warning(f"Error validating last region: {e}")
            return None

    
    def clamp_rect_to_desktop(self, rect):
        """Clamp a rectangle to fit within the full desktop bounds"""
        min_x = self.full_desktop_offset.x()
        min_y = self.full_desktop_offset.y()
        max_x = min_x + self.width()
        max_y = min_y + self.height()
        
        x = max(min_x, min(rect.x(), max_x - rect.width()))
        y = max(min_y, min(rect.y(), max_y - rect.height()))
        
        return QRect(int(x), int(y), rect.width(), rect.height())
    
    def setup_full_desktop_geometry(self):
        """Set geometry to cover all monitors"""
        min_x = min_y = float('inf')
        max_x = max_y = float('-inf')
        
        for screen in self.screens:
            geom = screen.geometry()
            min_x = min(min_x, geom.x())
            min_y = min(min_y, geom.y())
            max_x = max(max_x, geom.x() + geom.width())
            max_y = max(max_y, geom.y() + geom.height())
        
        width = int(max_x - min_x)
        height = int(max_y - min_y)
        
        self.setGeometry(int(min_x), int(min_y), width, height)
        self.full_desktop_offset = QPoint(int(min_x), int(min_y))
        
        logger.info(f"Full desktop geometry set: x={int(min_x)}, y={int(min_y)}, w={width}, h={height}")
    
    def capture_screens(self):
        """Capture all screens into a single pixmap"""
        try:
            width = self.width()
            height = self.height()
            self.screen_pixmap = QPixmap(width, height)
            self.screen_pixmap.fill(Qt.black)
            
            painter = QPainter(self.screen_pixmap)
            for screen in self.screens:
                geom = screen.geometry()
                screen_shot = screen.grabWindow(0)
                x = geom.x() - self.full_desktop_offset.x()
                y = geom.y() - self.full_desktop_offset.y()
                painter.drawPixmap(int(x), int(y), screen_shot)
            painter.end()
        except Exception as e:
            logger.error(f"Error capturing screens: {e}")
    
    def paintEvent(self, event):
        painter = QPainter(self)
        
        # Draw the full screenshot with reduced opacity outside capture area
        if hasattr(self, 'screen_pixmap'):
            # Draw full screen pixmap
            painter.drawPixmap(0, 0, self.screen_pixmap)
            
            # Darken areas outside the capture rectangle
            # Create a path for everything except the capture area
            path_painter = QPainter(self.screen_pixmap)
            
            # Draw semi-transparent dark overlay only on areas outside capture rect
            dark_color = QColor(0, 0, 0, 100)  # Lighter opacity (100 instead of 180)
            
            # Darken top area
            if self.capture_rect.top() > 0:
                painter.fillRect(0, 0, self.width(), self.capture_rect.top(), dark_color)
            
            # Darken bottom area
            if self.capture_rect.bottom() < self.height():
                painter.fillRect(0, self.capture_rect.bottom(), self.width(), 
                               self.height() - self.capture_rect.bottom(), dark_color)
            
            # Darken left area
            if self.capture_rect.left() > 0:
                painter.fillRect(0, self.capture_rect.top(), self.capture_rect.left(), 
                               self.capture_rect.height(), dark_color)
            
            # Darken right area
            if self.capture_rect.right() < self.width():
                painter.fillRect(self.capture_rect.right(), self.capture_rect.top(), 
                               self.width() - self.capture_rect.right(), 
                               self.capture_rect.height(), dark_color)
        
        # Draw border around capture area
        pen = QPen(QColor(147, 51, 234), 4)
        painter.setPen(pen)
        painter.drawRect(self.capture_rect)
        
        # Draw corner and edge handles for resizing
        handle_size = 10
        painter.setBrush(QColor(147, 51, 234))
        
        # Draw corner handles
        corners = [
            self.capture_rect.topLeft(),
            self.capture_rect.topRight(),
            self.capture_rect.bottomLeft(),
            self.capture_rect.bottomRight()
        ]
        for corner in corners:
            painter.drawEllipse(corner.x() - handle_size, corner.y() - handle_size, 
                              handle_size * 2, handle_size * 2)
        
        # Draw edge handles
        edges = [
            QPoint(self.capture_rect.center().x(), self.capture_rect.top()),  # top
            QPoint(self.capture_rect.center().x(), self.capture_rect.bottom()),  # bottom
            QPoint(self.capture_rect.left(), self.capture_rect.center().y()),  # left
            QPoint(self.capture_rect.right(), self.capture_rect.center().y())  # right
        ]
        for edge in edges:
            painter.drawRect(edge.x() - handle_size // 2, edge.y() - handle_size // 2,
                           handle_size, handle_size)
        
        # Draw dimensions label
        painter.setPen(Qt.white)
        dim_text = f"{self.capture_rect.width()} × {self.capture_rect.height()} px"
        text_rect = painter.fontMetrics().boundingRect(dim_text)
        text_x = self.capture_rect.center().x() - text_rect.width() // 2
        text_y = self.capture_rect.top() - 20
        
        bg_rect = QRect(text_x - 10, text_y - text_rect.height() - 5, 
                       text_rect.width() + 20, text_rect.height() + 10)
        painter.fillRect(bg_rect, QColor(147, 51, 234))
        painter.drawText(text_x, text_y, dim_text)
        
        instructions = "ENTER = Capture  |  ESC = Cancel  |  Drag to move  |  Drag edges/corners to resize"
        inst_rect = painter.fontMetrics().boundingRect(instructions)
        inst_x = self.width() // 2 - inst_rect.width() // 2
        inst_y = self.height() - 50
        
        inst_bg = QRect(inst_x - 20, inst_y - inst_rect.height() - 10,
                       inst_rect.width() + 40, inst_rect.height() + 20)
        painter.fillRect(inst_bg, QColor(30, 41, 59, 230))
        painter.drawText(inst_x, inst_y, instructions)
    
    def get_resize_edge(self, pos):
        """Determine which edge or corner is being hovered/clicked"""
        handle_size = 15
        
        # Check corners first
        corners = {
            'tl': self.capture_rect.topLeft(),
            'tr': self.capture_rect.topRight(),
            'bl': self.capture_rect.bottomLeft(),
            'br': self.capture_rect.bottomRight()
        }
        
        for corner_name, corner_pos in corners.items():
            if self.distance(pos, corner_pos) <= handle_size:
                return corner_name
        
        # Check edges
        handle_margin = 15
        
        if abs(pos.y() - self.capture_rect.top()) <= handle_margin and \
           self.capture_rect.left() <= pos.x() <= self.capture_rect.right():
            return 't'
        
        if abs(pos.y() - self.capture_rect.bottom()) <= handle_margin and \
           self.capture_rect.left() <= pos.x() <= self.capture_rect.right():
            return 'b'
        
        if abs(pos.x() - self.capture_rect.left()) <= handle_margin and \
           self.capture_rect.top() <= pos.y() <= self.capture_rect.bottom():
            return 'l'
        
        if abs(pos.x() - self.capture_rect.right()) <= handle_margin and \
           self.capture_rect.top() <= pos.y() <= self.capture_rect.bottom():
            return 'r'
        
        return None
    
    def distance(self, p1, p2):
        """Calculate distance between two points"""
        return ((p1.x() - p2.x()) ** 2 + (p1.y() - p2.y()) ** 2) ** 0.5
    
    def get_resize_cursor(self, edge):
        """Get appropriate cursor for resize edge"""
        cursor_map = {
            'tl': Qt.SizeFDiagCursor,
            'tr': Qt.SizeBDiagCursor,
            'bl': Qt.SizeBDiagCursor,
            'br': Qt.SizeFDiagCursor,
            't': Qt.SizeVerCursor,
            'b': Qt.SizeVerCursor,
            'l': Qt.SizeHorCursor,
            'r': Qt.SizeHorCursor
        }
        return cursor_map.get(edge, Qt.ArrowCursor)
    
    def mousePressEvent(self, event):
        # Check if clicking on resize handle
        resize_edge = self.get_resize_edge(event.pos())
        if resize_edge:
            self.resizing = True
            self.resize_edge = resize_edge
            self.resize_start_pos = event.pos()
            self.resize_start_rect = QRect(self.capture_rect)
            self.setCursor(self.get_resize_cursor(resize_edge))
        # Check if clicking inside rectangle for dragging
        elif self.capture_rect.contains(event.pos()):
            self.dragging = True
            self.drag_offset = event.pos() - self.capture_rect.topLeft()
            self.setCursor(Qt.ClosedHandCursor)
    
    def mouseMoveEvent(self, event):
        if self.resizing:
            # Calculate the change in position
            dx = event.pos().x() - self.resize_start_pos.x()
            dy = event.pos().y() - self.resize_start_pos.y()
            
            new_rect = QRect(self.resize_start_rect)
            
            # Handle corner and edge resizing
            if self.resize_edge == 'tl':
                new_rect.setTopLeft(new_rect.topLeft() + QPoint(dx, dy))
            elif self.resize_edge == 'tr':
                new_rect.setTopRight(new_rect.topRight() + QPoint(dx, dy))
            elif self.resize_edge == 'bl':
                new_rect.setBottomLeft(new_rect.bottomLeft() + QPoint(dx, dy))
            elif self.resize_edge == 'br':
                new_rect.setBottomRight(new_rect.bottomRight() + QPoint(dx, dy))
            elif self.resize_edge == 't':
                new_rect.setTop(new_rect.top() + dy)
            elif self.resize_edge == 'b':
                new_rect.setBottom(new_rect.bottom() + dy)
            elif self.resize_edge == 'l':
                new_rect.setLeft(new_rect.left() + dx)
            elif self.resize_edge == 'r':
                new_rect.setRight(new_rect.right() + dx)
            
            # Ensure minimum size
            if new_rect.width() >= self.resize_min_size and new_rect.height() >= self.resize_min_size:
                # Clamp to desktop bounds
                new_rect = self.clamp_rect_to_desktop(new_rect)
                self.capture_rect = new_rect
                self.update()
        
        elif self.dragging:
            # Calculate new position based on drag offset
            new_pos = event.pos() - self.drag_offset
            
            # Clamp within the full desktop bounds
            min_x = 0
            min_y = 0
            max_x = self.width() - self.capture_rect.width()
            max_y = self.height() - self.capture_rect.height()
            
            new_pos.setX(max(min_x, min(new_pos.x(), max_x)))
            new_pos.setY(max(min_y, min(new_pos.y(), max_y)))
            self.capture_rect.moveTo(new_pos)
            self.update()
        
        else:
            # Update cursor based on hover position
            resize_edge = self.get_resize_edge(event.pos())
            if resize_edge:
                self.setCursor(self.get_resize_cursor(resize_edge))
            elif self.capture_rect.contains(event.pos()):
                self.setCursor(Qt.OpenHandCursor)
            else:
                self.setCursor(Qt.CrossCursor)
    
    def mouseReleaseEvent(self, event):
        if self.resizing:
            self.resizing = False
            self.resize_edge = None
            # Emit signal to update UI with new dimensions
            self.update_ui_dimensions.emit(self.capture_rect.width(), self.capture_rect.height())
            # Update cursor after releasing
            resize_edge = self.get_resize_edge(event.pos())
            if resize_edge:
                self.setCursor(self.get_resize_cursor(resize_edge))
            elif self.capture_rect.contains(event.pos()):
                self.setCursor(Qt.OpenHandCursor)
            else:
                self.setCursor(Qt.CrossCursor)
        elif self.dragging:
            self.dragging = False
            # Update cursor after releasing
            if self.capture_rect.contains(event.pos()):
                self.setCursor(Qt.OpenHandCursor)
            else:
                self.setCursor(Qt.CrossCursor)
    
    def keyPressEvent(self, event):
        if not event.isAutoRepeat():  # Ignore key repeat events
            if event.key() == Qt.Key_Return or event.key() == Qt.Key_Enter:
                self.capture_and_save()
            elif event.key() == Qt.Key_Escape:
                self.close()
    
    def closeEvent(self, event):
        """Release mouse and keyboard grab when closing"""
        try:
            self.releaseMouse()
            self.releaseKeyboard()
        except:
            pass
        super().closeEvent(event)
    
    def get_next_sequence_number(self, save_dir, prefix):
        """
        Scan the save directory for files matching the prefix pattern
        and return the next sequence number.
        Pattern: prefix1.png, prefix2.png, etc.
        """
        import re
        
        if not os.path.exists(save_dir):
            return 1
        
        # Pattern to match: prefix followed by a number and .png extension
        pattern = re.compile(rf'^{re.escape(prefix)}(\d+)\.png$', re.IGNORECASE)
        
        max_number = 0
        try:
            for filename in os.listdir(save_dir):
                match = pattern.match(filename)
                if match:
                    number = int(match.group(1))
                    max_number = max(max_number, number)
        except Exception as e:
            logger.warning(f"Error scanning directory for sequence numbers: {e}")
        
        return max_number + 1
    
    def capture_and_save(self):
        try:
            # Release mouse and keyboard grabs BEFORE showing dialog
            self.releaseMouse()
            self.releaseKeyboard()
            
            captured = self.screen_pixmap.copy(self.capture_rect)
            
            save_dir = self.settings.get('save_location', 
                                        os.path.join(os.path.expanduser('~'), 'Screenshots'))
            os.makedirs(save_dir, exist_ok=True)
            
            # Get the file prefix from settings
            prefix = self.settings.get('file_prefix', '').strip()
            
            # If prefix is empty, use timestamp (original behavior)
            if not prefix:
                timestamp = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
                filename = f"Portrait_{timestamp}.png"
            else:
                # Use prefix with sequence number
                seq_number = self.get_next_sequence_number(save_dir, prefix)
                filename = f"{prefix}{seq_number}.png"
            
            filepath = os.path.join(save_dir, filename)
            
            if captured.save(filepath, 'PNG'):
                # Save the current capture region for next time
                self.save_capture_region()
                
                # Copy to clipboard if enabled
                if self.settings.get('copy_to_clipboard', True):
                    self.copy_image_to_clipboard(captured)
                
                self.capture_signal.emit(self.capture_rect)
                # Show a toast-like notification that auto-dismisses
                self.show_toast_notification(f"Screenshot saved:\n{filepath}")
            else:
                # Show error message with auto-dismiss
                self.show_toast_notification("Failed to save screenshot", is_error=True, duration=3000)
        except Exception as e:
            logger.error(f"Error during capture: {e}")
            self.show_toast_notification(f"Capture failed: {str(e)}", is_error=True, duration=3000)
        finally:
            self.close()
    
    def copy_image_to_clipboard(self, pixmap):
        """Copy the pixmap image to system clipboard"""
        try:
            clipboard = QApplication.clipboard()
            clipboard.setPixmap(pixmap)
            logger.info("Image copied to clipboard")
        except Exception as e:
            logger.error(f"Error copying to clipboard: {e}")
    
    def show_toast_notification(self, message, is_error=False, duration=2000):
        """Show a temporary notification that auto-dismisses"""
        from PyQt5.QtWidgets import QLabel, QFrame
        from PyQt5.QtCore import Qt, QTimer
        
        # Create a frame for the notification
        toast = QFrame()
        toast.setWindowFlags(Qt.Window | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        
        # Style the notification with semi-transparent background
        if is_error:
            bg_color = "#dc2626"  # Red
            text_color = "white"
        else:
            bg_color = "#10b981"  # Green
            text_color = "white"
        
        toast.setStyleSheet(f"""
            QFrame {{
                background-color: {bg_color};
                border-radius: 8px;
                padding: 15px 25px;
            }}
        """)
        
        # Create label for message
        label = QLabel(message)
        label.setStyleSheet(f"color: {text_color}; font-weight: bold; font-size: 13px;")
        label.setAlignment(Qt.AlignCenter)
        
        # Set layout
        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(label)
        toast.setLayout(layout)
        
        # Adjust size with some padding
        toast.adjustSize()
        
        # Set opacity to 0.95 (95% visible, 5% transparent)
        toast.setWindowOpacity(0.95)
        
        # Position at bottom center of screen
        screen = QApplication.primaryScreen()
        screen_geom = screen.geometry()
        toast_width = toast.width()
        toast_height = toast.height()
        
        x = screen_geom.x() + (screen_geom.width() - toast_width) // 2
        y = screen_geom.y() + screen_geom.height() - toast_height - 50
        
        toast.move(x, y)
        toast.raise_()
        toast.activateWindow()
        toast.show()
        
        # Keep a reference to prevent garbage collection
        if not hasattr(self, '_active_toasts'):
            self._active_toasts = []
        self._active_toasts.append(toast)
        
        # Auto-close after specified duration
        def close_toast():
            toast.close()
            if toast in self._active_toasts:
                self._active_toasts.remove(toast)
        
        QTimer.singleShot(duration, close_toast)
    
    def save_capture_region(self):
        """Save the current capture region to settings (separate for portrait/landscape)"""
        try:
            rect_data = {
                'x': self.capture_rect.x(),
                'y': self.capture_rect.y(),
                'width': self.capture_rect.width(),
                'height': self.capture_rect.height()
            }
            
            # Determine ratio mode based on dimensions
            ratio_mode = '9:16' if self.capture_rect.width() < self.capture_rect.height() else '16:9'
            region_key = f'last_capture_rect_{ratio_mode}'
            
            self.settings[region_key] = rect_data
            logger.info(f"Saved {ratio_mode} capture region: {rect_data}")
        except Exception as e:
            logger.error(f"Error saving capture region: {e}")


class PortraitScreenshotApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.settings = self.load_settings()
        self.overlay = None
        self.hotkey_thread = None
        self.is_exiting = False
        
        self.setWindowTitle("Portrait Screenshot Tool v1.9.0")
        self.setGeometry(300, 300, 450, 350)
        
        self.init_ui()
        self.init_tray()
        
        # Use a timer for hotkey registration to avoid blocking
        QTimer.singleShot(500, self.register_hotkey)
    
    def load_settings(self):
        settings_file = os.path.join(os.path.expanduser('~'), '.portrait_screenshot_settings.json')
        default_settings = {
            'hotkey': 'ctrl+shift+p',
            'save_location': os.path.join(os.path.expanduser('~'), 'Screenshots'),
            'portrait_width': 607,
            'portrait_height': 1080,
            'ratio_mode': '9:16',  # NEW: Track current ratio mode
            'lock_ratio': True,    # NEW: Track if ratio is locked
            'last_capture_rect': None,  # DEPRECATED: kept for backwards compatibility
            'copy_to_clipboard': True,
            'file_prefix': '',
            'profiles': {}
        }
        
        try:
            if os.path.exists(settings_file):
                with open(settings_file, 'r') as f:
                    loaded = json.load(f)
                    default_settings.update(loaded)
        except Exception as e:
            logger.warning(f"Error loading settings: {e}")
        
        return default_settings
    
    def save_settings(self):
        settings_file = os.path.join(os.path.expanduser('~'), '.portrait_screenshot_settings.json')
        try:
            with open(settings_file, 'w') as f:
                json.dump(self.settings, f, indent=2)
        except Exception as e:
            logger.error(f"Error saving settings: {e}")
    
    def init_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout()
        layout.setSpacing(15)
        
        title = QLabel("Portrait Screenshot Tool")
        title.setStyleSheet("font-size: 18px; font-weight: bold;")
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)
        
        # ── Profiles ──────────────────────────────────────────────────────────
        profiles_group = QGroupBox("Profiles")
        profiles_layout = QHBoxLayout()

        profiles_layout.addWidget(QLabel("Profile:"))
        self.profile_combo = QComboBox()
        self.profile_combo.setMinimumWidth(150)
        self.profile_combo.addItem("— select profile —")
        for name in sorted(self.settings.get('profiles', {}).keys()):
            self.profile_combo.addItem(name)
        profiles_layout.addWidget(self.profile_combo, 3)

        load_profile_btn = QPushButton("Load")
        load_profile_btn.setToolTip("Load the selected profile")
        load_profile_btn.clicked.connect(self.load_profile)
        profiles_layout.addWidget(load_profile_btn)

        save_profile_btn = QPushButton("Save as…")
        save_profile_btn.setToolTip("Save current settings as a new profile")
        save_profile_btn.clicked.connect(self.save_profile)
        profiles_layout.addWidget(save_profile_btn)

        delete_profile_btn = QPushButton("Delete")
        delete_profile_btn.setToolTip("Delete the selected profile")
        delete_profile_btn.clicked.connect(self.delete_profile)
        profiles_layout.addWidget(delete_profile_btn)

        profiles_group.setLayout(profiles_layout)
        layout.addWidget(profiles_group)
        # ──────────────────────────────────────────────────────────────────────

        settings_group = QGroupBox("Settings")
        settings_layout = QVBoxLayout()
        
        hotkey_layout = QHBoxLayout()
        hotkey_layout.addWidget(QLabel("Hotkey:"))
        self.hotkey_input = QLineEdit(self.settings['hotkey'])
        self.hotkey_input.setPlaceholderText("e.g., ctrl+shift+p")
        hotkey_layout.addWidget(self.hotkey_input)
        settings_layout.addLayout(hotkey_layout)
        
        save_layout = QHBoxLayout()
        save_layout.addWidget(QLabel("Save to:"))
        self.save_input = QLineEdit(self.settings['save_location'])
        browse_btn = QPushButton("Browse")
        browse_btn.clicked.connect(self.browse_folder)
        save_layout.addWidget(self.save_input, 3)
        save_layout.addWidget(browse_btn, 1)
        settings_layout.addLayout(save_layout)
        
        # File prefix input
        prefix_layout = QHBoxLayout()
        prefix_layout.addWidget(QLabel("File prefix:"))
        self.prefix_input = QLineEdit(self.settings.get('file_prefix', ''))
        self.prefix_input.setPlaceholderText("Leave empty for timestamp, or enter prefix (e.g., picture, screenshot)")
        prefix_layout.addWidget(self.prefix_input)
        settings_layout.addLayout(prefix_layout)
        
        dims_layout = QHBoxLayout()
        dims_layout.addWidget(QLabel("Width:"))
        self.width_spin = QSpinBox()
        self.width_spin.setRange(100, 4000)
        self.width_spin.setValue(self.settings['portrait_width'])
        self.width_spin.valueChanged.connect(self.on_width_changed)
        dims_layout.addWidget(self.width_spin)
        
        dims_layout.addWidget(QLabel("Height:"))
        self.height_spin = QSpinBox()
        self.height_spin.setRange(100, 4000)
        self.height_spin.setValue(self.settings['portrait_height'])
        self.height_spin.valueChanged.connect(self.on_height_changed)
        dims_layout.addWidget(self.height_spin)
        settings_layout.addLayout(dims_layout)
        
        # Aspect ratio lock and mode selection
        ratio_lock_layout = QHBoxLayout()
        self.lock_ratio_checkbox = QCheckBox("Lock Aspect Ratio")
        self.lock_ratio_checkbox.setChecked(self.settings.get('lock_ratio', True))
        self.lock_ratio_checkbox.stateChanged.connect(self.on_lock_ratio_changed)
        ratio_lock_layout.addWidget(self.lock_ratio_checkbox)
        
        # Radio buttons for ratio selection
        self.ratio_group = QButtonGroup()
        self.ratio_9_16 = QRadioButton("9:16 (Portrait)")
        self.ratio_16_9 = QRadioButton("16:9 (Landscape)")
        
        self.ratio_group.addButton(self.ratio_9_16)
        self.ratio_group.addButton(self.ratio_16_9)
        
        if self.settings.get('ratio_mode', '9:16') == '9:16':
            self.ratio_9_16.setChecked(True)
        else:
            self.ratio_16_9.setChecked(True)
        
        self.ratio_9_16.toggled.connect(self.on_ratio_mode_changed)
        self.ratio_16_9.toggled.connect(self.on_ratio_mode_changed)
        
        ratio_lock_layout.addWidget(self.ratio_9_16)
        ratio_lock_layout.addWidget(self.ratio_16_9)
        ratio_lock_layout.addStretch()
        settings_layout.addLayout(ratio_lock_layout)
        
        # Update the ratio label to show current state
        self.ratio_label = QLabel()
        self.update_ratio_label()
        self.ratio_label.setStyleSheet("color: #10b981; font-size: 10px; font-style: italic;")
        settings_layout.addWidget(self.ratio_label)
        
        # Enable/disable ratio buttons based on lock state
        self.on_lock_ratio_changed()
        
        # NEW: Show last capture region status
        self.last_region_label = QLabel()
        self.update_last_region_label()
        self.last_region_label.setStyleSheet("color: #3b82f6; font-size: 10px; font-style: italic;")
        settings_layout.addWidget(self.last_region_label)
        
        # NEW: Clipboard copy option
        clipboard_layout = QHBoxLayout()
        self.copy_to_clipboard_checkbox = QCheckBox("Copy screenshot to clipboard")
        self.copy_to_clipboard_checkbox.setChecked(self.settings.get('copy_to_clipboard', True))
        clipboard_layout.addWidget(self.copy_to_clipboard_checkbox)
        clipboard_layout.addStretch()
        settings_layout.addLayout(clipboard_layout)
        
        save_settings_btn = QPushButton("Save Settings")
        save_settings_btn.clicked.connect(self.apply_settings)
        settings_layout.addWidget(save_settings_btn)
        
        settings_group.setLayout(settings_layout)
        layout.addWidget(settings_group)
        
        btn_layout = QHBoxLayout()
        
        capture_btn = QPushButton("Capture Now")
        capture_btn.setStyleSheet("padding: 10px; font-weight: bold;")
        capture_btn.clicked.connect(self.start_capture)
        btn_layout.addWidget(capture_btn)
        
        minimize_btn = QPushButton("Minimize to Tray")
        minimize_btn.clicked.connect(self.hide)
        btn_layout.addWidget(minimize_btn)
        
        layout.addLayout(btn_layout)
        
        exit_btn = QPushButton("Exit Application")
        exit_btn.setStyleSheet("background-color: #dc2626; color: white; padding: 8px;")
        exit_btn.clicked.connect(self.quit_app)
        layout.addWidget(exit_btn)
        
        info = QLabel(f"Press {self.settings['hotkey'].upper()} to capture\nRuns in system tray when minimized")
        info.setStyleSheet("color: gray; font-size: 10px;")
        info.setAlignment(Qt.AlignCenter)
        layout.addWidget(info)
        
        central_widget.setLayout(layout)
    
    def update_last_region_label(self):
        """Update label showing last capture region status for both modes"""
        portrait_rect = self.settings.get('last_capture_rect_9:16')
        landscape_rect = self.settings.get('last_capture_rect_16:9')
        
        labels = []
        if portrait_rect:
            labels.append(f"Portrait (9:16): {portrait_rect['width']}×{portrait_rect['height']} at ({portrait_rect['x']}, {portrait_rect['y']})")
        if landscape_rect:
            labels.append(f"Landscape (16:9): {landscape_rect['width']}×{landscape_rect['height']} at ({landscape_rect['x']}, {landscape_rect['y']})")
        
        if labels:
            self.last_region_label.setText("Last regions: " + " | ".join(labels))
        else:
            self.last_region_label.setText("No previous capture regions saved")
    
    def browse_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Save Location")
        if folder:
            self.save_input.setText(folder)
    
    def on_width_changed(self, value):
        # Only update height if ratio is locked
        if self.settings.get('lock_ratio', True):
            self.height_spin.blockSignals(True)
            if self.settings.get('ratio_mode', '9:16') == '9:16':
                new_height = int(value * 16 / 9)
            else:  # 16:9
                new_height = int(value * 9 / 16)
            self.height_spin.setValue(new_height)
            self.height_spin.blockSignals(False)
            self.update_ratio_label()
    
    def on_height_changed(self, value):
        # Only update width if ratio is locked
        if self.settings.get('lock_ratio', True):
            self.width_spin.blockSignals(True)
            if self.settings.get('ratio_mode', '9:16') == '9:16':
                new_width = int(value * 9 / 16)
            else:  # 16:9
                new_width = int(value * 16 / 9)
            self.width_spin.setValue(new_width)
            self.width_spin.blockSignals(False)
            self.update_ratio_label()
    
    def on_lock_ratio_changed(self):
        """Handle lock ratio checkbox state change"""
        is_locked = self.lock_ratio_checkbox.isChecked()
        self.settings['lock_ratio'] = is_locked
        
        # Enable/disable ratio mode buttons
        self.ratio_9_16.setEnabled(is_locked)
        self.ratio_16_9.setEnabled(is_locked)
        
        # If locking, adjust dimensions to match current ratio mode
        if is_locked:
            if self.settings.get('ratio_mode', '9:16') == '9:16':
                self.on_width_changed(self.width_spin.value())
            else:
                self.on_width_changed(self.width_spin.value())
        
        self.update_ratio_label()
            
    def on_ratio_mode_changed(self, checked):
        """Handle ratio mode change (9:16 or 16:9) with default dimensions"""
        if not checked:  # Skip when button is being unchecked
            return
        
        # Temporarily store and disable ratio lock to prevent interference
        was_locked = self.settings.get('lock_ratio', True)
        self.settings['lock_ratio'] = False
        
        # Block signals on both spin boxes
        self.width_spin.blockSignals(True)
        self.height_spin.blockSignals(True)
        
        if self.ratio_9_16.isChecked():
            self.settings['ratio_mode'] = '9:16'
            # Set portrait mode defaults: 607x1080
            default_width = 607
            default_height = 1080
        else:
            self.settings['ratio_mode'] = '16:9'
            # Set landscape mode defaults: 1920x1080
            default_width = 1920
            default_height = 1080
        
        # Update the spin boxes with default values
        self.width_spin.setValue(default_width)
        self.height_spin.setValue(default_height)
        
        # Update settings
        self.settings['portrait_width'] = default_width
        self.settings['portrait_height'] = default_height
        
        # Restore ratio lock
        self.settings['lock_ratio'] = was_locked
        
        # Unblock signals
        self.width_spin.blockSignals(False)
        self.height_spin.blockSignals(False)
        
        self.update_ratio_label()

    
    def update_ratio_label(self):
        """Update the ratio information label"""
        if self.settings.get('lock_ratio', True):
            mode = self.settings.get('ratio_mode', '9:16')
            if mode == '9:16':
                self.ratio_label.setText("Ratio: 9:16 (Portrait - YouTube Shorts/TikTok/Instagram)")
            else:
                self.ratio_label.setText("Ratio: 16:9 (Landscape - YouTube/Standard Video)")
        else:
            width = self.width_spin.value()
            height = self.height_spin.value()
            self.ratio_label.setText(f"Custom dimensions: {width} × {height} px (ratio unlocked)")
    
    # ── Profile management ────────────────────────────────────────────────────

    def _profile_settings_snapshot(self):
        """Return a dict of the settings that belong in a profile."""
        keys = [
            'hotkey', 'save_location', 'file_prefix',
            'portrait_width', 'portrait_height',
            'ratio_mode', 'lock_ratio', 'copy_to_clipboard',
            'last_capture_rect_9:16', 'last_capture_rect_16:9',
        ]
        return {k: self.settings[k] for k in keys if k in self.settings}

    def save_profile(self):
        """Prompt the user for a name and save the current settings as a profile."""
        name, ok = QInputDialog.getText(
            self, "Save Profile", "Profile name:",
        )
        if not ok or not name.strip():
            return
        name = name.strip()

        # First apply any unsaved UI changes into self.settings
        self.settings['hotkey'] = self.hotkey_input.text()
        self.settings['save_location'] = self.save_input.text()
        self.settings['file_prefix'] = self.prefix_input.text()
        self.settings['portrait_width'] = self.width_spin.value()
        self.settings['portrait_height'] = self.height_spin.value()
        self.settings['lock_ratio'] = self.lock_ratio_checkbox.isChecked()
        self.settings['ratio_mode'] = '9:16' if self.ratio_9_16.isChecked() else '16:9'
        self.settings['copy_to_clipboard'] = self.copy_to_clipboard_checkbox.isChecked()

        if 'profiles' not in self.settings:
            self.settings['profiles'] = {}
        self.settings['profiles'][name] = self._profile_settings_snapshot()
        self.save_settings()

        # Update the combo box
        if self.profile_combo.findText(name) == -1:
            self.profile_combo.addItem(name)
            # Re-sort: rebuild the list
            all_names = sorted(
                self.settings['profiles'].keys()
            )
            self.profile_combo.clear()
            self.profile_combo.addItem("— select profile —")
            for n in all_names:
                self.profile_combo.addItem(n)

        # Select the saved profile in the dropdown
        idx = self.profile_combo.findText(name)
        if idx >= 0:
            self.profile_combo.setCurrentIndex(idx)

        QMessageBox.information(self, "Profile Saved", f'Profile "{name}" saved successfully!')

    def load_profile(self):
        """Load the selected profile into the UI."""
        name = self.profile_combo.currentText()
        if name == "— select profile —" or not name:
            QMessageBox.warning(self, "No Profile Selected", "Please select a profile from the dropdown first.")
            return

        profiles = self.settings.get('profiles', {})
        if name not in profiles:
            QMessageBox.warning(self, "Profile Not Found", f'Profile "{name}" could not be found.')
            return

        data = profiles[name]

        # Apply the stored values into settings
        self.settings.update(data)

        # Refresh UI widgets
        self.hotkey_input.setText(self.settings.get('hotkey', 'ctrl+shift+p'))
        self.save_input.setText(self.settings.get('save_location', ''))
        self.prefix_input.setText(self.settings.get('file_prefix', ''))

        self.width_spin.blockSignals(True)
        self.height_spin.blockSignals(True)
        self.width_spin.setValue(self.settings.get('portrait_width', 607))
        self.height_spin.setValue(self.settings.get('portrait_height', 1080))
        self.width_spin.blockSignals(False)
        self.height_spin.blockSignals(False)

        self.lock_ratio_checkbox.setChecked(self.settings.get('lock_ratio', True))

        if self.settings.get('ratio_mode', '9:16') == '9:16':
            self.ratio_9_16.setChecked(True)
        else:
            self.ratio_16_9.setChecked(True)

        self.copy_to_clipboard_checkbox.setChecked(self.settings.get('copy_to_clipboard', True))

        self.update_ratio_label()
        self.update_last_region_label()

        # Persist and re-register hotkey if it changed
        old_hotkey = self.settings.get('hotkey')
        self.save_settings()
        if old_hotkey != self.hotkey_input.text():
            self.register_hotkey()

        QMessageBox.information(self, "Profile Loaded", f'Profile "{name}" loaded successfully!')

    def delete_profile(self):
        """Delete the selected profile."""
        name = self.profile_combo.currentText()
        if name == "— select profile —" or not name:
            QMessageBox.warning(self, "No Profile Selected", "Please select a profile from the dropdown first.")
            return

        reply = QMessageBox.question(
            self, "Delete Profile",
            f'Are you sure you want to delete the profile "{name}"?',
            QMessageBox.Yes | QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return

        profiles = self.settings.get('profiles', {})
        if name in profiles:
            del profiles[name]
            self.save_settings()

        idx = self.profile_combo.findText(name)
        if idx >= 0:
            self.profile_combo.removeItem(idx)

        self.profile_combo.setCurrentIndex(0)

    # ─────────────────────────────────────────────────────────────────────────

    def apply_settings(self):
        old_hotkey = self.settings['hotkey']
        
        self.settings['hotkey'] = self.hotkey_input.text()
        self.settings['save_location'] = self.save_input.text()
        self.settings['file_prefix'] = self.prefix_input.text()
        self.settings['portrait_width'] = self.width_spin.value()
        self.settings['portrait_height'] = self.height_spin.value()
        self.settings['lock_ratio'] = self.lock_ratio_checkbox.isChecked()
        self.settings['ratio_mode'] = '9:16' if self.ratio_9_16.isChecked() else '16:9'
        self.settings['copy_to_clipboard'] = self.copy_to_clipboard_checkbox.isChecked()
        
        self.save_settings()
        
        if old_hotkey != self.settings['hotkey']:
            self.register_hotkey()
        
        self.tray_icon.setToolTip(f"Portrait Screenshot\nPress {self.settings['hotkey'].upper()}")
        
        QMessageBox.information(self, "Settings Saved", "Your settings have been saved successfully!")
    
    def init_tray(self):
        self.tray_icon = QSystemTrayIcon(self)
        
        icon_pixmap = QPixmap(64, 64)
        icon_pixmap.fill(QColor(147, 51, 234))
        self.tray_icon.setIcon(QIcon(icon_pixmap))
        
        tray_menu = QMenu()
        
        capture_action = QAction("Capture", self)
        capture_action.triggered.connect(self.start_capture)
        tray_menu.addAction(capture_action)
        
        show_action = QAction("Show Window", self)
        show_action.triggered.connect(self.show)
        tray_menu.addAction(show_action)
        
        tray_menu.addSeparator()
        
        quit_action = QAction("Exit", self)
        quit_action.triggered.connect(self.quit_app)
        tray_menu.addAction(quit_action)
        
        self.tray_icon.setContextMenu(tray_menu)
        self.tray_icon.activated.connect(self.on_tray_click)
        self.tray_icon.show()
        
        self.tray_icon.setToolTip(f"Portrait Screenshot\nPress {self.settings['hotkey'].upper()}")
    
    def on_tray_click(self, reason):
        if reason == QSystemTrayIcon.Trigger and not self.isVisible():
            self.show()
            self.activateWindow()
    
    def register_hotkey(self):
        """Register hotkey in a separate thread to avoid blocking UI"""
        if self.is_exiting:
            return
        
        try:
            # Stop previous hotkey thread if exists
            if self.hotkey_thread is not None:
                self.hotkey_thread.stop()
                self.hotkey_thread = None
            
            # Create and start new hotkey thread
            self.hotkey_thread = HotkeyThread(self.settings['hotkey'])
            self.hotkey_thread.hotkey_triggered.connect(self.start_capture)
            self.hotkey_thread.start()
            
            logger.info(f"Hotkey registered: {self.settings['hotkey']}")
        except Exception as e:
            logger.error(f"Could not register hotkey: {e}")
            QMessageBox.warning(self, "Hotkey Error", 
                              f"Could not register hotkey: {self.settings['hotkey']}\n{str(e)}")
    
    def start_capture(self):
        """Start capture with safety checks"""
        if self.is_exiting:
            return
        
        try:
            if self.overlay is None or not self.overlay.isVisible():
                self.overlay = CaptureOverlay(self.settings)
                self.overlay.capture_signal.connect(self.on_capture_complete)
                self.overlay.update_ui_dimensions.connect(self.on_overlay_dimensions_changed)
                self.overlay.show()
                self.overlay.activateWindow()
                self.overlay.raise_()
        except Exception as e:
            logger.error(f"Error starting capture: {e}")
    
    def on_capture_complete(self, rect):
        """Called when capture is completed"""
        # Update the last region label
        self.update_last_region_label()
        # Save settings to persist the last region
        self.save_settings()
    
    def on_overlay_dimensions_changed(self, width, height):
        """Update UI dimensions when user resizes the capture rectangle"""
        self.width_spin.blockSignals(True)
        self.height_spin.blockSignals(True)
        
        self.width_spin.setValue(width)
        self.height_spin.setValue(height)
        
        self.width_spin.blockSignals(False)
        self.height_spin.blockSignals(False)
        
        self.update_ratio_label()
    
    def quit_app(self):
        reply = QMessageBox.question(self, 'Exit', 
                                     'Are you sure you want to exit?',
                                     QMessageBox.Yes | QMessageBox.No)
        if reply == QMessageBox.Yes:
            self.close()
    
    def closeEvent(self, event):
        """Handle app closure safely"""
        # If we're already exiting, force close
        if self.is_exiting:
            event.accept()
            return
        
        self.is_exiting = True
        
        # Stop hotkey thread
        try:
            if self.hotkey_thread is not None:
                self.hotkey_thread.stop()
                self.hotkey_thread = None
        except Exception as e:
            logger.error(f"Error stopping hotkey thread: {e}")
        
        # Close overlay if open
        if self.overlay and self.overlay.isVisible():
            self.overlay.close()
        
        # Hide tray icon
        try:
            self.tray_icon.hide()
        except Exception as e:
            logger.error(f"Error hiding tray icon: {e}")
        
        # Accept the close event
        event.accept()
        
        # Schedule application quit after cleanup
        QTimer.singleShot(100, QApplication.quit)


def main():
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    
    window = PortraitScreenshotApp()
    window.show()
    
    sys.exit(app.exec_())


if __name__ == '__main__':
    main()