import sys
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QHBoxLayout, QLabel, QComboBox, QPushButton, QDialog, QFileDialog,
                             QScrollArea, QFrame, QProgressBar, QDesktopWidget, QSizePolicy,
                             QGraphicsDropShadowEffect, QGraphicsOpacityEffect, QToolTip)
from PyQt5.QtCore import Qt, QTimer, QPropertyAnimation, QEasingCurve, QEvent
from PyQt5.QtGui import QFont, QPalette, QColor, QPixmap, QFontDatabase, QIcon
import os
import serial
import json
import serial.tools.list_ports
import time
from datetime import datetime
from resistance_calibration import (
    DEFAULT_CALIBRATION,
    DEFAULT_CALIBRATION_POINTS,
    resistance_from_voltage,
    solve_calibration_from_four_points,
)

# Configuration
BAUD_RATE = 115200
UPDATE_INTERVAL_MS = 50  # Serial/GUI update interval; lower = more responsive but heavier on event loop (smoother drag at 50ms)

# Short test: one (bg, fg) per group so multiple separate shorts get different colors (red, orange, yellow, ...)
SHORT_GROUP_COLORS = [
    ("#2a2020", "#F73B30"),   # red
    ("#2a2218", "#E67E22"),   # orange
    ("#2a2a18", "#F1C40F"),   # yellow
    ("#202a20", "#27AE60"),   # green (if many groups)
]

def resource_path(relative_path):
    """Return absolute path to resource; works when running as script or as PyInstaller exe."""
    if getattr(sys, "frozen", False):
        base = sys._MEIPASS
    else:
        base = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, relative_path)


# Track if we've loaded the font and printed font info
_font_loaded = False
_font_info_printed = False
_marr_font_family = None

def load_font_from_file():
    """Load font from bundled file if available"""
    global _font_loaded, _marr_font_family
    
    if _font_loaded:
        return _marr_font_family
    
    font_name = "Marr Sans Cond Web Bold Regular.ttf"
    font_paths = [
        resource_path(font_name),
        resource_path(os.path.join("fonts", font_name)),
        os.path.join(os.path.dirname(__file__), font_name),
        os.path.join(os.path.dirname(sys.executable), font_name),
    ]
    
    for font_path in font_paths:
        if os.path.exists(font_path):
            try:
                font_id = QFontDatabase.addApplicationFont(font_path)
                if font_id != -1:
                    families = QFontDatabase.applicationFontFamilies(font_id)
                    if families:
                        _marr_font_family = families[0]
                        print(f"✓ Loaded font from file: '{_marr_font_family}'")
                        _font_loaded = True
                        return _marr_font_family
            except Exception as e:
                print(f"Error loading font from {font_path}: {e}")
    
    _font_loaded = True
    return None

def get_font(size=10, bold=False):
    """Get font with Marr Sans Condensed if available, fallback to system font"""
    global _marr_font_family, _font_info_printed
    
    # Try to load font from file first
    if not _font_loaded:
        load_font_from_file()
    
    # Try different font name variations
    marr_variations = [
        "Marr Sans Cond Web Bold",
        "Marr Sans Cond Web Bold Regular",
        "Marr Sans Cond",
        "Marr Sans Condensed"
    ]
    
    font_family = None
    if _marr_font_family:
        font_family = _marr_font_family
    else:
        # Try to find the font in system fonts
        available_fonts = QFontDatabase().families()
        for variation in marr_variations:
            if variation in available_fonts:
                font_family = variation
                break
    
    if font_family:
        font = QFont(font_family, size)
    else:
        # Fallback to system default
        font = QFont("Arial", size)
    
    if bold:
        font.setBold(True)
    
    return font

def add_drop_shadow(widget, blur=10, y_offset=2, alpha=50):
    """Apply a subtle drop shadow to a widget."""
    shadow = QGraphicsDropShadowEffect()
    shadow.setBlurRadius(blur)
    shadow.setXOffset(0)
    shadow.setYOffset(y_offset)
    shadow.setColor(QColor(0, 0, 0, alpha))
    widget.setGraphicsEffect(shadow)

class VoltageBar(QWidget):
    """Custom widget for displaying voltage as a progress bar"""
    def __init__(self, parent=None):
        super().__init__(parent)
        
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(5)
        
        # Progress bar for voltage visualization
        self.progress_bar = QProgressBar()
        self.progress_bar.setMinimum(0)
        self.progress_bar.setMaximum(5000)  # 0-5V in millivolts
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(False)  # No text on the bar itself
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                border: 1px solid #555;
                border-radius: 4px;
                background-color: #1a1a1a;
                min-height: 15px;
                padding: 0px;
            }
            QProgressBar::chunk {
                background-color: #cccccc;
                border-radius: 3px;
                margin: 0px;
                min-height: 14px;
            }
        """)
        self.progress_bar.setMinimumHeight(18)
        self.progress_bar.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        layout.addWidget(self.progress_bar, stretch=2)
        
        # Label for voltage reading (separate from bar)
        self.voltage_label = QLabel("0.000 V")
        self.voltage_label.setFont(get_font(9))
        self.voltage_label.setStyleSheet("color: #ffffff; border: none; background: transparent;")
        self.voltage_label.setMinimumWidth(48)
        self.voltage_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        layout.addWidget(self.voltage_label, stretch=0)
        
        self.current_voltage = 0.0
        
        # Animation for smooth voltage transitions (very fast, constant velocity)
        self.animation = QPropertyAnimation(self.progress_bar, b"value")
        self.animation.setDuration(40)  # Very fast: 40ms - short enough to be quick, long enough to be smooth
        # Use Linear easing for truly constant velocity (no acceleration/deceleration at all)
        linear_curve = QEasingCurve(QEasingCurve.Linear)
        self.animation.setEasingCurve(linear_curve)
        self.target_mv = 0
        
        # Connect animation finished signal to ensure value is set correctly
        self.animation.finished.connect(self._on_animation_finished)
        
    def _on_animation_finished(self):
        """Ensure the progress bar value is exactly at the target after animation"""
        self.progress_bar.setValue(self.target_mv)
        self.progress_bar.repaint()
        
    def set_voltage(self, voltage):
        """Set voltage value (in volts) with smooth animation"""
        # Skip work when value unchanged (reduces lag when many channels update every tick)
        if voltage == self.current_voltage:
            return
        # Convert to millivolts for progress bar
        target_mv = int(voltage * 1000)
        self.target_mv = target_mv
        
        # Update label immediately (no animation needed for text)
        self.voltage_label.setText("%.3f V" % voltage)
        
        # Get current value - use animated value if animation is running
        if self.animation.state() == QPropertyAnimation.Running:
            current_mv = self.progress_bar.value()  # Get current animated position
            # If new target is different, smoothly transition from current animated position
            if target_mv != current_mv:
                self.animation.stop()
                # Don't set value here - let animation continue from current position
                self.animation.setStartValue(current_mv)
                self.animation.setEndValue(target_mv)
                self.animation.start()
        else:
            # No animation running - check if we need to start one
            current_mv = self.progress_bar.value()
            if target_mv != current_mv:
                # Start new animation from current static value
                self.animation.setStartValue(current_mv)
                self.animation.setEndValue(target_mv)
                self.animation.start()
            else:
                # Value already correct, just ensure it's set
                self.progress_bar.setValue(target_mv)
        
        self.current_voltage = voltage


class StyledChoiceDialog(QDialog):
    def __init__(self, parent, title, message, choices):
        super().__init__(parent)
        self.choice_key = None
        self.setModal(True)
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        card = QFrame()
        card.setStyleSheet("""
            QFrame {
                background-color: #242021;
                border: 1px solid #555;
                border-radius: 14px;
            }
            QLabel {
                background: transparent;
                color: #ffffff;
            }
        """)
        add_drop_shadow(card, blur=18, y_offset=4, alpha=70)
        outer.addWidget(card)

        layout = QVBoxLayout(card)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(14)

        title_label = QLabel(title)
        title_label.setFont(get_font(12, bold=True))
        title_label.setStyleSheet("color: #ffffff; border: none; background: transparent;")
        layout.addWidget(title_label)

        message_label = QLabel(message)
        message_label.setWordWrap(True)
        message_label.setFont(get_font(10))
        message_label.setStyleSheet("""
            color: #d8d8d8;
            border: none;
            background: transparent;
            padding: 2px 0 0 0;
        """)
        layout.addWidget(message_label)

        button_row = QHBoxLayout()
        button_row.setSpacing(10)
        layout.addLayout(button_row)

        for key, label, primary in choices:
            btn = QPushButton(label)
            btn.setFont(get_font(10, bold=primary))
            btn.setMinimumHeight(36)
            btn.setStyleSheet("""
                QPushButton {
                    background-color: %s;
                    color: %s;
                    border: 1px solid %s;
                    border-radius: 8px;
                    padding: 8px 12px;
                }
                QPushButton:hover {
                    border: 1px solid #FFE27A;
                }
            """ % (("#FED541" if primary else "#2a2a2a"), ("#1a1a1a" if primary else "#ffffff"), ("#FFE27A" if primary else "#555")))
            btn.clicked.connect(lambda _=False, choice_key=key: self._finish(choice_key))
            button_row.addWidget(btn)

        self.setFixedWidth(500)

    def _finish(self, choice_key):
        self.choice_key = choice_key
        self.accept()


def show_styled_choice(parent, title, message, choices):
    dialog = StyledChoiceDialog(parent, title, message, choices)
    dialog.exec_()
    return dialog.choice_key

class ChannelWidget(QWidget):
    """Widget for displaying a single channel's information"""
    def __init__(self, channel_num, parent=None):
        super().__init__(parent)
        
        layout = QHBoxLayout(self)
        layout.setContentsMargins(5, 3, 5, 3)
        layout.setSpacing(10)
        
        # Channel label (bubble) - wrapped for fade-in animation
        self.channel_label_wrapper = QWidget()
        self.channel_label_wrapper.setStyleSheet("background: transparent;")
        channel_wrapper_layout = QVBoxLayout(self.channel_label_wrapper)
        channel_wrapper_layout.setContentsMargins(0, 0, 0, 0)
        self.channel_label = QLabel("Y%d" % channel_num)
        self.channel_label.setFont(get_font(10))
        self.channel_label.setStyleSheet("""
            QLabel {
                background-color: #2a2a2a;
                color: #ffffff;
                padding: 6px;
                border-radius: 6px;
                border: 1px solid transparent;
            }
        """)
        self.channel_label.setMinimumWidth(100)
        self.channel_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.channel_label.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Preferred)
        channel_wrapper_layout.addWidget(self.channel_label)
        # Opacity effect on wrapper for fade-in animation when channel fails
        self.channel_opacity = QGraphicsOpacityEffect(self.channel_label_wrapper)
        self.channel_label_wrapper.setGraphicsEffect(self.channel_opacity)
        self.channel_opacity.setOpacity(1.0)  # Start at full opacity
        self.channel_fade_anim = QPropertyAnimation(self.channel_opacity, b"opacity")
        self.channel_fade_anim.setDuration(267)  # 1.5x faster than 400ms
        self.channel_fade_anim.setEasingCurve(QEasingCurve.Linear)  # Linear is faster than OutCubic
        self.channel_label_wrapper.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Preferred)
        self._channel_is_failing = False  # Track if we're currently in fail state
        layout.addWidget(self.channel_label_wrapper, stretch=1)
        
        # Voltage bar — same column width as Channel and Status (equal stretch)
        self.voltage_bar = VoltageBar()
        self.voltage_bar.setMinimumWidth(60)
        self.voltage_bar.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        layout.addWidget(self.voltage_bar, stretch=1)
        
        # Resistance label (to the right of voltage)
        self.resistance_label = QLabel("---")
        self.resistance_label.setFont(get_font(9))
        self.resistance_label.setStyleSheet("""
            QLabel {
                background-color: #242021;
                color: #ffffff;
                padding: 6px;
                border-radius: 6px;
                border: 1px solid transparent;
            }
        """)
        self.resistance_label.setMinimumWidth(80)
        self.resistance_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.resistance_label.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Preferred)
        layout.addWidget(self.resistance_label, stretch=1)
        # Hidden by default until user confirms resistance board
        self.resistance_label.setVisible(False)
        
        # Status label (bubble)
        self.status_label = QLabel("---")
        self.status_label.setFont(get_font(10, bold=True))
        self.status_label.setStyleSheet("""
            QLabel {
                background-color: #2a2a2a;
                color: #ffffff;
                padding: 6px;
                border-radius: 6px;
                border: 1px solid transparent;
            }
        """)
        self.status_label.setMinimumWidth(110)
        self.status_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.status_label.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Preferred)
        layout.addWidget(self.status_label, stretch=1)
        
        self.setStyleSheet("background-color: #242021;")
        # No drop shadow on channel rows - many effects cause QPainter "one painter at a time" errors
        # Cache last displayed values to skip redundant updates (reduces lag with many channels)
        self._last_voltage = None
        self._last_status = None
        self._last_display = None
        self._last_short_color = None
        self._last_resistance = None
        self._last_resistance_mode = None
        self._last_resistance_ready = None

    def update_data(self, voltage, status, signal_name=None, resistance=None, short_color=None, resistance_color=None, resistance_mode=False, resistance_ready=False):
        """Update the channel display with new data. short_color=(bg_hex, fg_hex) for short-group highlight."""
        # Skip full update when nothing changed (avoids stylesheet/repaint storm when device sends often)
        display = signal_name
        if self._last_voltage == voltage and self._last_status == status and self._last_display == display and self._last_short_color == short_color and self._last_resistance == resistance and self._last_resistance_mode == resistance_mode and self._last_resistance_ready == resistance_ready:
            return
        self._last_voltage = voltage
        self._last_status = status
        self._last_display = display
        self._last_short_color = short_color
        self._last_resistance = resistance
        self._last_resistance_mode = resistance_mode
        self._last_resistance_ready = resistance_ready

        self.voltage_bar.set_voltage(voltage)
        if resistance is None:
            self.resistance_label.setText("---")
        else:
            try:
                resistance_value = float(resistance)
                if resistance_value > 10000000:
                    self.resistance_label.setText("OPEN CIRCUIT")
                else:
                    self.resistance_label.setText("%0.1f \u2126" % resistance_value)
            except Exception:
                self.resistance_label.setText("---")
        self.resistance_label.setStyleSheet("""
            QLabel {
                background-color: #242021;
                color: #ffffff;
                padding: 6px;
                border-radius: 6px;
                border: 1px solid transparent;
            }
        """)

        if signal_name:
            self.channel_label.setText(signal_name)

        # Channel name highlight follows normal mode unless resistance mode is active.
        _channel_normal = """
            QLabel {
                background-color: #2a2a2a;
                color: #ffffff;
                padding: 6px;
                border-radius: 6px;
                border: 1px solid transparent;
            }
        """
        _channel_fail = """
            QLabel {
                background-color: #3d2020;
                color: #F73B30;
                padding: 6px;
                border-radius: 6px;
                border: 1px solid #F73B30;
            }
        """
        if short_color and isinstance(short_color, (tuple, list)) and len(short_color) >= 2:
            bg, fg = short_color[0], short_color[1]
            _channel_short = """
                QLabel {
                    background-color: %s;
                    color: %s;
                    padding: 6px;
                    border-radius: 6px;
                    border: 1px solid %s;
                }
            """ % (bg, fg, fg)
        else:
            _channel_short = _channel_fail
        is_short = bool(status and status.startswith("shorted with"))
        is_fail = status.upper() == "FAIL" or is_short
        if resistance_mode:
            channel_style = _channel_short if (is_short and short_color) else _channel_normal
            should_highlight_channel = is_short
        else:
            channel_style = _channel_short if (is_fail and short_color) else (_channel_fail if is_fail else _channel_normal)
            should_highlight_channel = is_fail
        if should_highlight_channel:
            # Only animate if transitioning TO fail state (not if already failing)
            if not self._channel_is_failing:
                self.channel_label.setStyleSheet(channel_style)
                if self.channel_fade_anim.state() == QPropertyAnimation.Running:
                    self.channel_fade_anim.stop()
                self.channel_opacity.setOpacity(0.0)
                self.channel_fade_anim.setStartValue(0.0)
                self.channel_fade_anim.setEndValue(1.0)
                self.channel_fade_anim.start()
                self._channel_is_failing = True
            elif self.channel_label.styleSheet() != channel_style:
                self.channel_label.setStyleSheet(channel_style)
            if self.channel_fade_anim.state() != QPropertyAnimation.Running:
                self.channel_opacity.setOpacity(1.0)
        else:
            if self._channel_is_failing:
                self.channel_fade_anim.stop()
                self.channel_opacity.setOpacity(1.0)
                self.channel_label.setStyleSheet(_channel_normal)
                self._channel_is_failing = False
            else:
                self.channel_label.setStyleSheet(_channel_normal)

        # In resistance mode, the status bubble becomes a color-only indicator.
        status_fg = short_color[1] if (short_color and isinstance(short_color, (tuple, list)) and len(short_color) >= 2) else "#F73B30"
        if resistance_mode and not is_short and status != "not testable yet":
            self.status_label.setText("")
            if (resistance is None) or (not resistance_ready):
                mode_color = "#555555"
            else:
                mode_color = resistance_color if resistance_color else "#E74C3C"
            self.status_label.setStyleSheet("""
                QLabel {
                    background-color: %s;
                    color: transparent;
                    padding: 6px;
                    border-radius: 6px;
                    border: 1px solid transparent;
                }
            """ % mode_color)
        elif status.upper() == "PASS":
            self.status_label.setText("PASS")
            self.status_label.setStyleSheet("""
                QLabel {
                    background-color: #2a2a2a;
                    color: #0d8c5a;
                    padding: 6px;
                    border-radius: 6px;
                    border: 1px solid transparent;
                }
            """)
        elif status.upper() == "FAIL":
            self.status_label.setText("FAIL")
            self.status_label.setStyleSheet("""
                QLabel {
                    background-color: #2a2a2a;
                    color: #F73B30;
                    padding: 6px;
                    border-radius: 6px;
                    border: 1px solid transparent;
                }
            """)
        elif status and status != "---" and (status.startswith("shorted with") or status not in ("PASS", "not testable yet")):
            self.status_label.setText(status)
            self.status_label.setStyleSheet("""
                QLabel {
                    background-color: #2a2a2a;
                    color: %s;
                    padding: 6px;
                    border-radius: 6px;
                    border: 1px solid transparent;
                }
            """ % status_fg)
        elif status == "not testable yet":
            self.status_label.setText("not testable yet")
            self.status_label.setStyleSheet("""
                QLabel {
                    background-color: #2a2a2a;
                    color: #888;
                    padding: 6px;
                    border-radius: 6px;
                    border: 1px solid transparent;
                }
            """)
        else:
            self.status_label.setText("---")
            self.status_label.setStyleSheet("""
                QLabel {
                    background-color: #2a2a2a;
                    color: #ffffff;
                    padding: 6px;
                    border-radius: 6px;
                    border: 1px solid transparent;
                }
            """)

    def set_resistance_visible(self, visible: bool):
        """Show or hide the resistance label for this channel."""
        self.resistance_label.setVisible(visible)
    
    def reset(self):
        """Reset the channel display to default state (no voltage, no status)"""
        self._last_voltage = None
        self._last_status = None
        self._last_display = None
        self._last_short_color = None
        self._last_resistance = None
        self._last_resistance_mode = None
        self._last_resistance_ready = None
        self.voltage_bar.set_voltage(0.0)
        self.channel_fade_anim.stop()
        self.channel_opacity.setOpacity(1.0)
        self._channel_is_failing = False
        self.channel_label.setStyleSheet("""
            QLabel {
                background-color: #2a2a2a;
                color: #ffffff;
                padding: 6px;
                border-radius: 6px;
                border: 1px solid transparent;
            }
        """)
        self.status_label.setText("---")
        self.status_label.setStyleSheet("""
            QLabel {
                background-color: #2a2a2a;
                color: #ffffff;
                padding: 6px;
                border-radius: 6px;
                border: 1px solid transparent;
            }
        """)
        # Reset resistance display
        try:
            self._last_resistance = None
            self.resistance_label.setVisible(False)
        except Exception:
            pass
    
    def set_voltage_visible(self, visible):
        """Show or hide the voltage bar (e.g. hide in Compute Distro short mode)."""
        self.voltage_bar.setVisible(visible)

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.calibration = dict(DEFAULT_CALIBRATION)
        self.latest_channel_readings = {}
        self.pending_calibration_voltage = None
        desktop_dir = os.path.join(os.path.expanduser("~"), "Desktop")
        self.last_export_dir = desktop_dir if os.path.isdir(desktop_dir) else os.path.expanduser("~")
        self.setWindowTitle("EV3 Flex Tester")
        # Taskbar icon (Windows): use .ico for best quality, or PNG logo
        _icon_paths = [
            resource_path("favicon.ico"),
            resource_path("icon.ico"),
            resource_path("Zipline_Logo_Vertical_White.png"),
        ]
        for p in _icon_paths:
            if os.path.exists(p):
                self.setWindowIcon(QIcon(p))
                break
        
        # Get screen size and set window size responsively
        screen = QDesktopWidget().screenGeometry()
        screen_width = screen.width()
        screen_height = screen.height()
        
        # Set window size to 80% of screen or minimum 800x600, whichever is larger
        window_width = max(800, int(screen_width * 0.8))
        window_height = max(600, int(screen_height * 0.8))
        
        # Center the window
        x = (screen_width - window_width) // 2
        y = (screen_height - window_height) // 2
        
        self.setGeometry(x, y, window_width, window_height)
        
        # Remove default title bar and create custom one
        self.setWindowFlags(Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        
        # Set dark theme (central widget will draw rounded corners; main window is transparent)
        self.setStyleSheet("""
            QMainWindow {
                background: transparent;
            }
            QWidget {
                background-color: #242021;
                color: #ffffff;
            }
        """)
        
        # Central widget with rounded corners
        central_widget = QWidget()
        central_widget.setStyleSheet("background-color: #242021; border-radius: 14px;")
        self.setCentralWidget(central_widget)
        
        # Main layout (with title bar at top)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        
        # Create custom title bar
        self.create_title_bar()
        main_layout.addWidget(self.title_bar)
        
        # Content layout
        content_layout = QHBoxLayout()
        content_layout.setContentsMargins(15, 15, 15, 15)
        content_layout.setSpacing(15)
        
        # Left sidebar
        sidebar = QWidget()
        sidebar.setMinimumWidth(220)
        sidebar.setMaximumWidth(220)
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(10, 10, 10, 10)
        sidebar_layout.setSpacing(15)
        
        # Logo (bundled with exe or next to script)
        logo_label = QLabel()
        logo_path = resource_path("Zipline_Logo_Vertical_White.png")
        try:
            pixmap = QPixmap(logo_path)
            # Scale logo smaller (keeping aspect ratio)
            if not pixmap.isNull():
                scaled_pixmap = pixmap.scaled(120, 140, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                logo_label.setPixmap(scaled_pixmap)
                logo_label.setAlignment(Qt.AlignCenter)
        except Exception as e:
            print(f"Could not load logo: {e}")
        sidebar_layout.addWidget(logo_label)
        
        # Header
        header = QLabel("EV3 Flex Tester")
        header.setFont(get_font(14, bold=True))
        header.setStyleSheet("""
            QLabel {
                background-color: #242021;
                color: #ffffff;
                padding: 10px;
                border-radius: 3px;
                border: none;
            }
        """)
        header.setAlignment(Qt.AlignCenter)
        header.setWordWrap(True)
        # Remove any drop shadow effects
        header.setGraphicsEffect(None)
        sidebar_layout.addWidget(header)
        
        # Test selection dropdown
        test_label = QLabel("Select test")
        test_label.setFont(get_font(11, bold=True))
        sidebar_layout.addWidget(test_label)
        
        self.test_combo = QComboBox()
        self.test_combo.addItems(["AoA/Pitot Test", "Compute Distro Test", "Hover Aft Flex Test", "Hover Fore Flex Test", "Camera Flex Test"])
        self.test_combo.setFont(get_font(10))
        self.test_combo.setStyleSheet("""
            QComboBox {
                background-color: #242021;
                color: #ffffff;
                border: 1px solid #555;
                border-radius: 6px;
                padding: 6px 8px;
            }
            QComboBox:hover {
                border: 1px solid #666;
                padding: 7px 9px;
            }
            QComboBox::drop-down {
                border: none;
                width: 25px;
                background-color: transparent;
            }
            QComboBox::down-arrow {
                width: 0px;
                height: 0px;
                border-left: 4px solid transparent;
                border-right: 4px solid transparent;
                border-top: 5px solid #ffffff;
                margin-right: 8px;
            }
            QComboBox QAbstractItemView {
                background-color: #242021;
                color: #ffffff;
                selection-background-color: #0066ff;
            }
        """)
        add_drop_shadow(self.test_combo, blur=8, y_offset=2, alpha=45)
        self.test_combo.currentTextChanged.connect(self.on_test_change)
        sidebar_layout.addWidget(self.test_combo)
        
        # Flex test mode: Continuity / Short (for Hover Fore Flex and Hover Aft Flex)
        self.flex_mode_row = QWidget()
        self.flex_mode_row.setStyleSheet("background: transparent;")
        flex_mode_layout = QHBoxLayout(self.flex_mode_row)
        flex_mode_layout.setContentsMargins(0, 6, 0, 0)
        flex_mode_layout.setSpacing(8)
        self.flex_continuity_btn = QPushButton("Continuity")
        self.flex_short_btn = QPushButton("Short")
        for btn in (self.flex_continuity_btn, self.flex_short_btn):
            btn.setFont(get_font(10))
            btn.setStyleSheet("""
                QPushButton {
                    background-color: #2a2a2a;
                    color: #ffffff;
                    border: 1px solid #555;
                    border-radius: 6px;
                    padding: 6px 10px;
                }
                QPushButton:hover {
                    border: 1px solid #666;
                }
                QPushButton:checked {
                    background-color: #FED541;
                    color: #1a1a1a;
                    border: 2px solid #FFE27A;
                    font-weight: 700;
                }
            """)
            btn.setCheckable(True)
        self.flex_continuity_btn.setChecked(True)
        self.flex_continuity_btn.clicked.connect(lambda: self._set_flex_mode("continuity"))
        self.flex_short_btn.clicked.connect(lambda: self._set_flex_mode("short"))
        flex_mode_layout.addWidget(self.flex_continuity_btn)
        flex_mode_layout.addWidget(self.flex_short_btn)
        self.flex_short_mode = False

        self.board_type = "continuity"
        self.resistance_enabled = False
        self.calibration_loaded = False
        self.calibrate_btn = QPushButton("Calibrate")
        self.calibrate_btn.setFont(get_font(10))
        self.calibrate_btn.setStyleSheet("""
            QPushButton {
                background-color: #2a2a2a;
                color: #ffffff;
                border: 1px solid #555;
                border-radius: 6px;
                padding: 6px 10px;
            }
            QPushButton:hover {
                border: 1px solid #666;
            }
        """)
        self.calibrate_btn.clicked.connect(self.calibrate_resistance_from_y15)
        self.calibrate_btn.setVisible(False)
        self.change_board_type_btn = QPushButton("Change Board Type")
        self.change_board_type_btn.setFont(get_font(9))
        self.change_board_type_btn.setMinimumHeight(40)
        self.change_board_type_btn.setStyleSheet("""
            QPushButton {
                background-color: #1f1b1c;
                color: #d8d8d8;
                border: 1px solid #444;
                border-radius: 6px;
                padding: 8px 12px;
                text-align: left;
            }
            QPushButton:hover {
                border: 1px solid #666;
                color: #ffffff;
            }
        """)
        self.change_board_type_btn.clicked.connect(self.prompt_change_board_type)

        # Camera Flex: Fore / Aft (only visible when Camera Flex Test selected)
        self.camera_fore_aft_row = QWidget()
        self.camera_fore_aft_row.setStyleSheet("background: transparent;")
        camera_fa_layout = QHBoxLayout(self.camera_fore_aft_row)
        camera_fa_layout.setContentsMargins(0, 6, 0, 0)
        camera_fa_layout.setSpacing(8)
        self.camera_fore_btn = QPushButton("Fore")
        self.camera_aft_btn = QPushButton("Aft")
        for btn in (self.camera_fore_btn, self.camera_aft_btn):
            btn.setFont(get_font(10))
            btn.setStyleSheet("""
                QPushButton {
                    background-color: #2a2a2a;
                    color: #ffffff;
                    border: 1px solid #555;
                    border-radius: 6px;
                    padding: 6px 10px;
                }
                QPushButton:hover { border: 1px solid #666; }
                QPushButton:checked {
                    background-color: #FED541;
                    color: #1a1a1a;
                    border: 2px solid #FFE27A;
                    font-weight: 700;
                }
            """)
            btn.setCheckable(True)
        self.camera_fore_btn.setChecked(True)
        self.camera_aft_enabled = True
        self.camera_aft_under_dev_msg = ""
        self.camera_fore_btn.clicked.connect(lambda: self._set_camera_fore_aft("fore"))
        self.camera_aft_btn.clicked.connect(lambda: self._set_camera_fore_aft("aft"))
        camera_fa_layout.addWidget(self.camera_fore_btn)
        camera_fa_layout.addWidget(self.camera_aft_btn)
        sidebar_layout.addWidget(self.camera_fore_aft_row)
        self.camera_fore_aft_row.setVisible(False)
        sidebar_layout.addWidget(self.flex_mode_row)
        self.flex_mode_row.setVisible(False)

        # Compute Distro mode: Continuity / Short (neutral style, only visible for Compute Distro)
        self.cdist_mode_row = QWidget()
        self.cdist_mode_row.setStyleSheet("background: transparent;")
        cdist_mode_layout = QHBoxLayout(self.cdist_mode_row)
        cdist_mode_layout.setContentsMargins(0, 6, 0, 0)
        cdist_mode_layout.setSpacing(8)
        self.continuity_btn = QPushButton("Continuity")
        self.short_btn = QPushButton("Short")
        for btn in (self.continuity_btn, self.short_btn):
            btn.setFont(get_font(10))
            btn.setStyleSheet("""
                QPushButton {
                    background-color: #2a2a2a;
                    color: #ffffff;
                    border: 1px solid #555;
                    border-radius: 6px;
                    padding: 6px 10px;
                }
                QPushButton:hover {
                    border: 1px solid #666;
                }
                QPushButton:checked {
                    background-color: #FED541;
                    color: #1a1a1a;
                    border: 2px solid #FFE27A;
                    font-weight: 700;
                }
            """)
            btn.setCheckable(True)
        self.continuity_btn.setChecked(True)
        self.continuity_btn.clicked.connect(lambda: self._set_cdist_mode("continuity"))
        self.short_btn.clicked.connect(lambda: self._set_cdist_mode("short"))
        cdist_mode_layout.addWidget(self.continuity_btn)
        cdist_mode_layout.addWidget(self.short_btn)
        sidebar_layout.addWidget(self.cdist_mode_row)
        self.cdist_mode_row.setVisible(False)
        self.cdist_short_mode = False
        sidebar_layout.addWidget(self.change_board_type_btn)
        sidebar_layout.addWidget(self.calibrate_btn)
        
        # Spacer
        sidebar_layout.addStretch()
        
        def _set_cdist_mode(mode):
            self.cdist_short_mode = (mode == "short")
            self.continuity_btn.setChecked(mode == "continuity")
            self.short_btn.setChecked(mode == "short")
            self.voltage_header_bubble.setVisible(not self.cdist_short_mode)
            if hasattr(self, "header_bubbles_column2") and self.header_bubbles_column2:
                self.header_bubbles_column2[1].setVisible(not self.cdist_short_mode)
            for w in self.channel_widgets.values():
                w.set_voltage_visible(not self.cdist_short_mode)
            if self.ser and self.ser.is_open:
                self.send_command("mode:%s" % mode)
        
        self._set_cdist_mode = _set_cdist_mode

        # Status label
        self.status_label = QLabel("No device found - Click Start to connect")
        self.status_label.setFont(get_font(10))
        self.status_label.setStyleSheet("color: #FED541;")
        self.status_label.setWordWrap(True)
        self.status_label.setMinimumHeight(40)
        sidebar_layout.addWidget(self.status_label)
        
        # Temporary: JSON receive indicator (debug)
        self.json_indicator_frame = QFrame()
        self.json_indicator_frame.setStyleSheet("""
            QFrame {
                background-color: #2a2a2a;
                border: 1px solid #555;
                border-radius: 8px;
                padding: 8px;
            }
        """)
        add_drop_shadow(self.json_indicator_frame, blur=6, y_offset=1, alpha=40)
        json_indicator_layout = QVBoxLayout(self.json_indicator_frame)
        json_indicator_layout.setContentsMargins(8, 8, 8, 8)
        self.json_indicator_label = QLabel("Receiving JSON: —")
        self.json_indicator_label.setFont(get_font(10, bold=True))
        self.json_indicator_label.setStyleSheet("color: #888;")
        self.json_indicator_label.setWordWrap(True)
        json_indicator_layout.addWidget(self.json_indicator_label)
        sidebar_layout.addWidget(self.json_indicator_frame)
        self.last_json_time = 0.0  # time when we last received valid JSON
        
        # Temporary: device connection indicator (debug)
        self.device_indicator_frame = QFrame()
        self.device_indicator_frame.setStyleSheet("""
            QFrame {
                background-color: #2a2a2a;
                border: 1px solid #555;
                border-radius: 8px;
                padding: 8px;
            }
        """)
        add_drop_shadow(self.device_indicator_frame, blur=6, y_offset=1, alpha=40)
        device_indicator_layout = QVBoxLayout(self.device_indicator_frame)
        device_indicator_layout.setContentsMargins(8, 8, 8, 8)
        self.device_indicator_label = QLabel("Device: —")
        self.device_indicator_label.setFont(get_font(10, bold=True))
        self.device_indicator_label.setStyleSheet("color: #888;")
        self.device_indicator_label.setWordWrap(True)
        device_indicator_layout.addWidget(self.device_indicator_label)
        sidebar_layout.addWidget(self.device_indicator_frame)
        
        # Control buttons
        button_layout = QVBoxLayout()
        button_layout.setSpacing(10)
        
        self.start_button = QPushButton("Start")
        self.start_button.setFont(get_font(11, bold=True))
        self.start_button.setStyleSheet("""
            QPushButton {
                background-color: #0d8c5a;
                color: #ffffff;
                border: none;
                border-radius: 6px;
                padding: 10px;
            }
            QPushButton:hover {
                background-color: #0fa866;
                padding: 12px;
            }
            QPushButton:pressed {
                padding: 8px;
            }
            QPushButton:disabled {
                background-color: #555;
                color: #888;
            }
        """)
        add_drop_shadow(self.start_button, blur=10, y_offset=3, alpha=55)
        self.start_button.clicked.connect(self.start_test)
        button_layout.addWidget(self.start_button)
        
        self.stop_button = QPushButton("Stop")
        self.stop_button.setFont(get_font(11, bold=True))
        self.stop_button.setEnabled(False)
        self.stop_button.setStyleSheet("""
            QPushButton {
                background-color: #F73B30;
                color: #ffffff;
                border: none;
                border-radius: 6px;
                padding: 10px;
            }
            QPushButton:hover {
                background-color: #ff4d40;
                padding: 12px;
            }
            QPushButton:pressed {
                padding: 8px;
            }
            QPushButton:disabled {
                background-color: #555;
                color: #888;
            }
        """)
        add_drop_shadow(self.stop_button, blur=10, y_offset=3, alpha=55)
        self.stop_button.clicked.connect(self.stop_test)
        button_layout.addWidget(self.stop_button)

        self.export_button = QPushButton("Export Results")
        self.export_button.setFont(get_font(11, bold=True))
        self.export_button.setStyleSheet("""
            QPushButton {
                background-color: #2a2a2a;
                color: #ffffff;
                border: 1px solid #555;
                border-radius: 6px;
                padding: 10px;
            }
            QPushButton:hover {
                border: 1px solid #666;
                padding: 12px;
            }
            QPushButton:pressed {
                padding: 8px;
            }
            QPushButton:disabled {
                background-color: #555;
                color: #888;
            }
        """)
        add_drop_shadow(self.export_button, blur=10, y_offset=3, alpha=55)
        self.export_button.clicked.connect(self.export_results)
        button_layout.addWidget(self.export_button)
        
        sidebar_layout.addLayout(button_layout)
        
        content_layout.addWidget(sidebar)
        
        # Main content area: one big bubble (data_bubble) containing headers + scroll, to separate from sidebar
        main_content = QWidget()
        main_content_layout = QVBoxLayout(main_content)
        main_content_layout.setContentsMargins(0, 0, 0, 0)
        main_content_layout.setSpacing(0)
        
        data_bubble = QFrame()
        data_bubble.setStyleSheet("""
            QFrame {
                background-color: #2a2a2a;
                border: 1px solid #555;
                border-radius: 12px;
                padding: 0;
            }
        """)
        data_bubble_layout = QVBoxLayout(data_bubble)
        data_bubble_layout.setContentsMargins(12, 12, 12, 12)
        data_bubble_layout.setSpacing(0)
        
        # Headers: optional PF/SF row + row of column titles (hidden entirely for Camera Flex)
        self.header_container = QWidget()
        self.header_container.setStyleSheet("background: transparent;")
        header_container_vbox = QVBoxLayout(self.header_container)
        header_container_vbox.setContentsMargins(0, 0, 0, 0)
        header_container_vbox.setSpacing(4)
        # PF/SF label row - shown only for Camera Flex, above the two columns
        self.pf_sf_row = QWidget()
        self.pf_sf_row.setStyleSheet("background: transparent;")
        self.pf_sf_row.setVisible(False)
        pf_sf_layout = QHBoxLayout(self.pf_sf_row)
        pf_sf_layout.setContentsMargins(0, 0, 0, 0)
        pf_sf_layout.setSpacing(10)
        pf_label = QLabel("PF")
        pf_label.setFont(get_font(11, bold=True))
        pf_label.setStyleSheet("color: #888; background: transparent; border: none;")
        sf_label = QLabel("SF")
        sf_label.setFont(get_font(11, bold=True))
        sf_label.setStyleSheet("color: #888; background: transparent; border: none;")
        pf_sf_layout.addWidget(pf_label, stretch=1)
        pf_sf_layout.addWidget(sf_label, stretch=1)
        header_container_vbox.addWidget(self.pf_sf_row)
        self.headers_widget = QWidget()
        self.headers_widget.setStyleSheet("background: transparent;")
        self.headers_layout = QHBoxLayout(self.headers_widget)
        self.headers_layout.setContentsMargins(0, 0, 0, 8)
        self.headers_layout.setSpacing(10)
        
        def _make_header_bubble(text, min_w, stretch=0):
            frame = QFrame()
            frame.setStyleSheet("""
                QFrame {
                    background-color: #242021;
                    border: 1px solid #555;
                    border-radius: 5px;
                    padding: 3px;
                }
            """)
            frame.setMinimumWidth(min_w)
            lay = QVBoxLayout(frame)
            lay.setContentsMargins(4, 2, 4, 2)
            label = QLabel(text)
            label.setFont(get_font(11, bold=True))
            label.setStyleSheet("color: #ffffff; background: transparent; border: none;")
            label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            lay.addWidget(label)
            return frame, label
        
        # Title bubbles: equal stretch so Channel, Voltage, Status columns are same width
        ch_bubble, self.channel_header = _make_header_bubble("Channel", 100)
        self.channel_header.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Preferred)
        self.headers_layout.addWidget(ch_bubble, stretch=1)
        
        v_bubble, self.voltage_header = _make_header_bubble("Voltage", 60)
        self.voltage_header_bubble = v_bubble
        self.voltage_header.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.headers_layout.addWidget(v_bubble, stretch=1)
        # Resistance header (new) - hidden by default
        res_bubble, self.resistance_header = _make_header_bubble("Resistance", 80)
        self.resistance_header_bubble = res_bubble
        self.resistance_header.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Preferred)
        self.headers_layout.addWidget(res_bubble, stretch=1)
        res_bubble.hide()

        s_bubble, self.status_header = _make_header_bubble("Status", 110)
        self.status_header.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Preferred)
        self.headers_layout.addWidget(s_bubble, stretch=1)
        
        # Second set of column title bubbles (for Compute Distro second column); parent so they never become separate windows
        ch_bubble2, self.channel_header2 = _make_header_bubble("Channel", 100)
        ch_bubble2.setParent(self.header_container)
        self.channel_header2.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Preferred)
        v_bubble2, self.voltage_header2 = _make_header_bubble("Voltage", 60)
        v_bubble2.setParent(self.header_container)
        self.voltage_header2.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        # Resistance second column (hidden by default)
        res_bubble2, self.resistance_header2 = _make_header_bubble("Resistance", 80)
        self.resistance_header_bubble2 = res_bubble2
        res_bubble2.setParent(self.header_container)
        self.resistance_header2.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Preferred)
        res_bubble2.hide()
        s_bubble2, self.status_header2 = _make_header_bubble("Status", 110)
        s_bubble2.setParent(self.header_container)
        self.status_header2.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Preferred)
        self.header_bubbles_column2 = [ch_bubble2, v_bubble2, res_bubble2, s_bubble2]
        for b in self.header_bubbles_column2:
            b.hide()
        # _setup_two_column_layout will add them to headers_layout when needed
        
        header_container_vbox.addWidget(self.headers_widget)
        data_bubble_layout.addWidget(self.header_container)
        
        # Scroll area for channels (stored so we can re-apply policies on resize/monitor change)
        self.channels_scroll_area = QScrollArea()
        self.channels_scroll_area.setWidgetResizable(True)
        self.channels_scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.channels_scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.channels_scroll_area.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.channels_scroll_area.setStyleSheet("""
            QScrollArea {
                background-color: #242021;
                border: none;
            }
            QScrollBar:vertical {
                background-color: #242021;
                width: 12px;
                border: none;
            }
            QScrollBar::handle:vertical {
                background-color: #555;
                border-radius: 6px;
                min-height: 20px;
            }
            QScrollBar::handle:vertical:hover {
                background-color: #666;
            }
        """)
        
        # Channels container
        self.channels_widget = QWidget()
        self.channels_layout = QVBoxLayout(self.channels_widget)
        self.channels_layout.setContentsMargins(5, 5, 5, 5)
        self.channels_layout.setSpacing(2)
        self.channels_layout.addStretch()  # Add stretch at end to push widgets to top
        
        # For two-column layout (compute distro) or quartered layout (camera flex)
        self.column1_layout = None
        self.column2_layout = None
        self.two_column_container = None
        self.camera_gnd_layout = None
        self.camera_flex_main_container = None
        
        self.channels_scroll_area.setWidget(self.channels_widget)
        data_bubble_layout.addWidget(self.channels_scroll_area)

        # Camera Fore Short alias warning (shown below channels in Camera Fore + Short mode)
        self.camera_short_alias_warning = QLabel(
            'WARNING, this test is unable to detect shorts between '
            '<span style="color:#F73B30; font-weight:700;">BLOWER_PF_A</span> and '
            '<span style="color:#F73B30; font-weight:700;">V_CAM_SF</span> '
            'due an demux alias pair. If issues persist, test these pins with a multimeter '
            'to verify any shorts.'
        )
        self.camera_short_alias_warning.setFont(get_font(10, bold=True))
        self.camera_short_alias_warning.setStyleSheet("color: #FED541; background: transparent; border: none;")
        self.camera_short_alias_warning.setWordWrap(True)
        data_bubble_layout.addWidget(self.camera_short_alias_warning)
        self.camera_short_alias_warning.setVisible(False)
        
        main_content_layout.addWidget(data_bubble)
        content_layout.addWidget(main_content, stretch=1)
        
        main_layout.addLayout(content_layout)
        
        # State variables
        self.channel_widgets = {}
        self.updating = False
        self.ser = None
        self.current_test = "aoa"
        self.valid_channels = [10, 11, 12, 13, 14, 15]
        self._dragging = False  # True while user is dragging window (pauses update_timer for smoother drag)
        
        # Signal name mappings for AoA/Pitot Test (P75/P94 connector pin numbers from schematic)
        self.aoa_signal_names = {
            10: "AirData_SCL_EXT_P",
            11: "AirData_SCL_EXT_N",
            12: "AirData_SDA_EXT_P",
            13: "AirData_12V6",
            14: "GND_AOA",
            15: "AirData_SDA_EXT_N"
        }
        self.aoa_channel_pins = {10: 7, 11: 9, 12: 3, 13: 5, 14: 6, 15: 1}  # channel -> P75/P94 pin
        
        # Signal name mappings for Compute Distro Test (C1-C30)
        # Pin mapping is REVERSED: Pin 1 → C30 (Y15, ADC1), Pin 30 → C1 (Y1, ADC0)
        self.compute_distro_signal_names = {
            1: "GND7",           # Pin 30 → C1 (Y1, ADC0)
            2: "COMP_D_GBE_P",   # Pin 29 → C2 (Y2, ADC0)
            3: "IMU_POCI_N",     # Pin 28 → C3 (Y3, ADC0)
            4: "COMP_D_GBE_N",   # Pin 27 → C4 (Y4, ADC0)
            5: "IMU_POCI_P",     # Pin 26 → C5 (Y5, ADC0)
            6: "COMP_C_GBE_P",   # Pin 25 → C6 (Y6, ADC0)
            7: "GND6",           # Pin 24 → C7 (Y7, ADC0)
            8: "COMP_C_GBE_N",   # Pin 23 → C8 (Y8, ADC0)
            9: "IMU_FSYNC_N",    # Pin 22 → C9 (Y9, ADC0)
            10: "COMP_B_GBE_P",  # Pin 21 → C10 (Y10, ADC0)
            11: "IMU_FSYNC_P",   # Pin 20 → C11 (Y11, ADC0)
            12: "COMP_B_GBE_N",  # Pin 19 → C12 (Y12, ADC0)
            13: "GND5",          # Pin 18 → C13 (Y13, ADC0)
            14: "COMP_A_GBE_P",  # Pin 17 → C14 (Y14, ADC0)
            15: "GND4",          # Pin 16 → C15 (Y15, ADC0)
            16: "COMP_A_GBE_N",  # Pin 15 → C16 (Y1, ADC1)
            17: "GND3",          # Pin 14 → C17 (Y2, ADC1)
            18: "VBUS4",         # Pin 13 → C18 (Y3, ADC1)
            19: "IMU_CS_P",      # Pin 12 → C19 (Y4, ADC1)
            20: "VBUS3",         # Pin 11 → C20 (Y5, ADC1)
            21: "IMU_CS_N",      # Pin 10 → C21 (Y6, ADC1)
            22: "VBUS2",         # Pin 9 → C22 (Y7, ADC1)
            23: "GND2",          # Pin 8 → C23 (Y8, ADC1)
            24: "VBUS1",         # Pin 7 → C24 (Y9, ADC1)
            25: "IMU_PICO_N",    # Pin 6 → C25 (Y10, ADC1)
            26: "IMU_5V",        # Pin 5 → C26 (Y11, ADC1)
            27: "IMU_PICO_P",    # Pin 4 → C27 (Y12, ADC1)
            28: "IMU_CLK_P",     # Pin 3 → C28 (Y13, ADC1)
            29: "GND1",          # Pin 2 → C29 (Y14, ADC1)
            30: "IMU_CLK_N"      # Pin 1 → C30 (Y15, ADC1)
        }
        # Hover Aft Flex Test: 10 channels (DEMUX→MUX pairs, DEMUX 1 for both GND and GND_SERVO)
        self.hover_aft_flex_signal_names = {
            1: "T1_IN_P",
            2: "28V_SERVO",
            3: "T1_IN_N",
            4: "GND1_HOVAFT",
            5: "GND2_HOVAFT",
            6: "RS485_P",
            7: "T1_OUT_P",
            8: "RS485_N",
            9: "T1_OUT_N",
            10: "CHASSIS"
        }
        # Hover Fore Flex Test: 7 channels (GND channels send N/A - show "not testable yet")
        self.hover_fore_flex_signal_names = {
            1: "T1_IN_P",
            2: "T1_IN_N",
            3: "T1_OUT_P",
            4: "T1_OUT_N",
            5: "CHASSIS"
        }
        self.hover_fore_flex_channel_order = (1, 2, 3, 4, 5)
        # Camera Flex Test: 20 channels (blower pins have no MUX - show "not testable yet")
        self.camera_flex_signal_names = {
            1: "GND8",
            2: "GND4",
            3: "GND7",
            4: "GMSL2_PF_N",
            5: "BLOWER_PF_A",
            6: "GMSL2_PF_P",
            7: "BLOWER_PF_B",
            8: "GND3",
            9: "BLOWER_PF_C",
            10: "V_CAM_PF",
            11: "BLOWER_SF_C",
            12: "GND2",
            13: "BLOWER_SF_B",
            14: "GMSL2_SF_N",
            15: "BLOWER_SF_A",
            16: "GMSL2_SF_P",
            17: "GND6",
            18: "GND1",
            19: "GND5",
            20: "V_CAM_SF"
        }
        # Camera Flex quartered layout: PF top-left, SF top-right (no GND in GUI)
        self.camera_flex_pf_channels = (4, 5, 6, 7, 9, 10)
        self.camera_flex_sf_channels = (11, 13, 14, 15, 16, 20)
        self.camera_flex_gnd_channels = (1, 2, 3, 8, 12, 17, 18, 19)
        # Camera Short (Fore): 12 channels, 1-12; PF = 1-6, SF = 7-12
        self.camera_short_pf_channels = (1, 2, 3, 4, 5, 6)
        self.camera_short_sf_channels = (7, 8, 9, 10, 11, 12)
        self.camera_short_signal_names = {
            1: "GMSL2_PF_N", 2: "BLOWER_PF_A", 3: "GMSL2_PF_P", 4: "BLOWER_PF_B",
            5: "BLOWER_PF_C", 6: "V_CAM_PF", 7: "BLOWER_SF_C", 8: "BLOWER_SF_B",
            9: "GMSL2_SF_N", 10: "BLOWER_SF_A", 11: "GMSL2_SF_P", 12: "V_CAM_SF"
        }
        # Camera Aft Flex (P52B): numbered to match Camera Flex tester DEMUX order
        self.camera_aft_flex_signal_names = {
            1: "GND", 2: "GND", 3: "GND", 4: "GMSL2_SF_N", 5: "BLOWER_SF_A", 6: "GMSL2_SF_P",
            7: "BLOWER_SF_B", 8: "GND", 9: "BLOWER_SF_C", 10: "V_CAM_SF", 11: "BLOWER_PF_C", 12: "GND",
            13: "BLOWER_PF_B", 14: "GMSL2_PF_N", 15: "BLOWER_PF_A", 16: "GMSL2_PF_P", 17: "GND", 18: "GND", 19: "GND", 20: "V_CAM_PF"
        }
        self.camera_aft_flex_pa_channels = (4, 5, 6, 7, 9, 10)
        self.camera_aft_flex_sa_channels = (11, 13, 14, 15, 16, 20)
        self.camera_aft_flex_gnd_channels = (1, 2, 3, 8, 12, 17, 18, 19)
        self.camera_aft_mode = False  # False = Fore (P52A), True = Aft (P52B)
        
        # Initialize with AoA/Pitot channels (default test)
        for ch_num in sorted([10, 11, 12, 13, 14, 15]):
            self.ensure_channel_display(ch_num)
        
        # Update timer
        self.update_timer = QTimer()
        self.update_timer.timeout.connect(self.update_gui)
        
        # Reconnection timer
        self.reconnect_timer = QTimer()
        self.reconnect_timer.timeout.connect(self.check_for_reconnection)
        
        # Timer to update JSON indicator (show "No" when nothing received for 2s)
        self.json_indicator_timer = QTimer()
        self.json_indicator_timer.timeout.connect(self._update_json_indicator)
        self.json_indicator_timer.start(500)
        
        # Event filter to detect mouse release after drag (restart update timer)
        QApplication.instance().installEventFilter(self)
        
        # Try to auto-detect serial on startup
        self.ser = self.auto_detect_serial(BAUD_RATE)
        if self.ser:
            self.status_label.setText("Device connected")
            self.status_label.setStyleSheet("color: #0d8c5a;")
        else:
            self.status_label.setText("No device found - Click Start to retry")
        
        # Apply initial test selection so Continuity/Short row is shown for AoA/Pitot (and others) on first load
        self.on_test_change(self.test_combo.currentText())
        self.status_label.setStyleSheet("color: #FED541;")
        self._apply_board_type_ui()
        
        # Constrain channel rows to viewport width so no horizontal scroll (run after first layout)
        QTimer.singleShot(0, self._constrain_channels_width)
        QTimer.singleShot(0, self.prompt_startup_board_type)
    
    def resizeEvent(self, event):
        """Constrain channel content to scroll viewport width so rows fit without horizontal scroll."""
        super().resizeEvent(event)
        self._constrain_channels_width()
    
    def _constrain_channels_width(self):
        """Set channels widget max width to scroll viewport width so content fits in window."""
        try:
            vw = self.channels_scroll_area.viewport().width()
            self.channels_widget.setMaximumWidth(max(100, vw))
        except Exception:
            pass
    
    def create_title_bar(self):
        """Create custom title bar for frameless window"""
        title_bar = QWidget()
        title_bar.setFixedHeight(40)
        title_bar.setStyleSheet("background-color: #242021;")
        
        title_layout = QHBoxLayout(title_bar)
        title_layout.setContentsMargins(10, 0, 0, 0)
        title_layout.setSpacing(10)
        
        # Title
        title_label = QLabel("EV3 Flex Tester")
        title_label.setFont(get_font(12, bold=True))
        title_label.setStyleSheet("color: #ffffff;")
        title_layout.addWidget(title_label)
        
        title_layout.addStretch()
        
        # Window controls
        minimize_btn = QPushButton("−")
        minimize_btn.setFixedSize(35, 35)
        minimize_btn.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                color: #ffffff;
                border: none;
                border-radius: 4px;
                font-size: 18px;
            }
            QPushButton:hover {
                background-color: #333;
                padding: 2px;
            }
            QPushButton:pressed {
                padding: 0px;
            }
        """)
        add_drop_shadow(minimize_btn, blur=4, y_offset=1, alpha=35)
        minimize_btn.clicked.connect(self.showMinimized)
        title_layout.addWidget(minimize_btn)
        
        close_btn = QPushButton("×")
        close_btn.setFixedSize(35, 35)
        close_btn.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                color: #ffffff;
                border: none;
                border-radius: 4px;
                font-size: 20px;
            }
            QPushButton:hover {
                background-color: #F73B30;
                padding: 2px;
            }
            QPushButton:pressed {
                padding: 0px;
            }
        """)
        add_drop_shadow(close_btn, blur=4, y_offset=1, alpha=35)
        close_btn.clicked.connect(self.close)
        title_layout.addWidget(close_btn)
        
        # Store title bar for dragging
        self.title_bar = title_bar
        # Make title bar draggable
        title_bar.mousePressEvent = self.title_bar_mouse_press
        title_bar.mouseMoveEvent = self.title_bar_mouse_move
    
    def title_bar_mouse_press(self, event):
        """Handle mouse press on title bar for window dragging"""
        if event.button() == Qt.LeftButton:
            self.drag_position = event.globalPos() - self.frameGeometry().topLeft()
            self._dragging = True
            if self.updating and self.update_timer.isActive():
                self.update_timer.stop()
            event.accept()
    
    def title_bar_mouse_move(self, event):
        """Handle mouse move on title bar for window dragging"""
        if event.buttons() == Qt.LeftButton and hasattr(self, 'drag_position'):
            self.move(event.globalPos() - self.drag_position)
            event.accept()
    
    def mousePressEvent(self, event):
        """Handle mouse press for window dragging"""
        if event.button() == Qt.LeftButton:
            self.drag_position = event.globalPos() - self.frameGeometry().topLeft()
            self._dragging = True
            if self.updating and self.update_timer.isActive():
                self.update_timer.stop()
            event.accept()
        super().mousePressEvent(event)
    
    def mouseMoveEvent(self, event):
        """Handle mouse move for window dragging only. Do not touch serial here."""
        if event.buttons() == Qt.LeftButton and hasattr(self, 'drag_position'):
            self.move(event.globalPos() - self.drag_position)
            event.accept()
        super().mouseMoveEvent(event)
    
    def eventFilter(self, obj, event):
        """Restart update timer when user releases mouse after dragging (smoother drag = less work during move)."""
        if obj == self.camera_aft_btn and event.type() == QEvent.Enter and not self.camera_aft_enabled:
            QToolTip.showText(self.camera_aft_btn.mapToGlobal(self.camera_aft_btn.rect().bottomLeft()),
                              self.camera_aft_under_dev_msg,
                              self.camera_aft_btn)
        if event.type() == QEvent.MouseButtonRelease and event.button() == Qt.LeftButton and self._dragging:
            self._dragging = False
            if self.updating and not self.update_timer.isActive():
                self.update_timer.start(UPDATE_INTERVAL_MS)
        return super().eventFilter(obj, event)
    
    def _setup_two_column_layout(self):
        """Set up two-column layout for compute distro or quartered layout for camera flex test"""
        # PF/SF row: hide for Camera Flex (quartered layout has its own Port Cam / Starboard Cam labels)
        self.pf_sf_row.setVisible(False)
        # Add second set of column title bubbles to headers row (remove first in case already present)
        for bubble in self.header_bubbles_column2:
            self.headers_layout.removeWidget(bubble)
        ch_bubble2, v_bubble2, res_bubble2, s_bubble2 = self.header_bubbles_column2
        self.headers_layout.addWidget(ch_bubble2, stretch=1)
        self.headers_layout.addWidget(v_bubble2, stretch=1)
        self.headers_layout.addWidget(res_bubble2, stretch=1)
        self.headers_layout.addWidget(s_bubble2, stretch=1)
        
        # Clear existing layout
        while self.channels_layout.count():
            item = self.channels_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        
        self.camera_gnd_layout = None
        self.camera_gnd_section = None
        self.camera_flex_main_container = None
        
        if self.current_test in ("camera_flex", "camera_short", "camera_aft_flex", "camera_aft_short"):
            # Quartered layout: PF/PA left, SF/SA right, GND bottom (GND hidden for camera_short Fore)
            self.header_container.hide()
            self._setup_camera_flex_quartered_layout()
        else:
            self.header_container.show()
            # Normal two columns for Compute Distro
            self.two_column_container = QWidget()
            two_column_layout = QHBoxLayout(self.two_column_container)
            two_column_layout.setContentsMargins(0, 0, 0, 0)
            two_column_layout.setSpacing(10)
            
            col1_widget = QWidget()
            self.column1_layout = QVBoxLayout(col1_widget)
            self.column1_layout.setContentsMargins(0, 0, 0, 0)
            self.column1_layout.setSpacing(2)
            self.column1_layout.addStretch()
            two_column_layout.addWidget(col1_widget, stretch=1)
            
            col2_widget = QWidget()
            self.column2_layout = QVBoxLayout(col2_widget)
            self.column2_layout.setContentsMargins(0, 0, 0, 0)
            self.column2_layout.setSpacing(2)
            self.column2_layout.addStretch()
            two_column_layout.addWidget(col2_widget, stretch=1)
            
            self.channels_layout.addWidget(self.two_column_container)
        self.channels_layout.addStretch()
    
    def _setup_camera_flex_quartered_layout(self):
        """Camera Flex: PF/PA top-left, SF/SA top-right (visible divider), GND bottom. Fore=PF/SF, Aft=PA/SA."""
        def _make_header_row():
            row = QWidget()
            row.setStyleSheet("background: transparent;")
            h = QHBoxLayout(row)
            h.setContentsMargins(0, 0, 0, 4)
            h.setSpacing(10)
            for text, min_w in [("Channel", 100), ("Voltage", 60), ("Resistance", 80), ("Status", 110)]:
                f = QFrame()
                f.setStyleSheet("QFrame { background-color: #242021; border: 1px solid #555; border-radius: 5px; padding: 3px; }")
                f.setMinimumWidth(min_w)
                lay = QVBoxLayout(f)
                lay.setContentsMargins(4, 2, 4, 2)
                lbl = QLabel(text)
                lbl.setFont(get_font(11, bold=True))
                lbl.setStyleSheet("color: #ffffff; background: transparent; border: none;")
                lay.addWidget(lbl)
                h.addWidget(f, stretch=1)
            return row
        
        is_aft = self.camera_aft_mode
        col1_label = "PA" if is_aft else "Port Cam"
        col2_label = "SA" if is_aft else "Starboard Cam"
        
        main = QWidget()
        main.setStyleSheet("background: transparent;")
        main_vbox = QVBoxLayout(main)
        main_vbox.setContentsMargins(0, 0, 0, 0)
        main_vbox.setSpacing(12)
        
        # Top half: col1 | divider | col2
        top_row = QWidget()
        top_row.setStyleSheet("background: transparent;")
        top_hbox = QHBoxLayout(top_row)
        top_hbox.setContentsMargins(0, 0, 0, 0)
        top_hbox.setSpacing(12)
        
        # Left section (PF or PA)
        pf_section = QWidget()
        pf_section.setStyleSheet("background: transparent;")
        pf_vbox = QVBoxLayout(pf_section)
        pf_vbox.setContentsMargins(0, 0, 8, 0)
        pf_vbox.setSpacing(4)
        pf_label = QLabel(col1_label)
        pf_label.setFont(get_font(12, bold=True))
        pf_label.setStyleSheet("color: #888; background: transparent; border: none;")
        pf_vbox.addWidget(pf_label)
        pf_vbox.addWidget(_make_header_row())
        self.column1_layout = QVBoxLayout()
        self.column1_layout.setContentsMargins(0, 0, 0, 0)
        self.column1_layout.setSpacing(2)
        self.column1_layout.addStretch()
        pf_vbox.addLayout(self.column1_layout)
        top_hbox.addWidget(pf_section, stretch=1)
        
        # Visible divider
        divider = QFrame()
        divider.setFrameShape(QFrame.VLine)
        divider.setLineWidth(3)
        divider.setStyleSheet("QFrame { color: #555; background-color: #555; max-width: 4px; }")
        divider.setFixedWidth(4)
        top_hbox.addWidget(divider, stretch=0)
        
        # Right section (SF or SA)
        sf_section = QWidget()
        sf_section.setStyleSheet("background: transparent;")
        sf_vbox = QVBoxLayout(sf_section)
        sf_vbox.setContentsMargins(8, 0, 0, 0)
        sf_vbox.setSpacing(4)
        sf_label = QLabel(col2_label)
        sf_label.setFont(get_font(12, bold=True))
        sf_label.setStyleSheet("color: #888; background: transparent; border: none;")
        sf_vbox.addWidget(sf_label)
        sf_vbox.addWidget(_make_header_row())
        self.column2_layout = QVBoxLayout()
        self.column2_layout.setContentsMargins(0, 0, 0, 0)
        self.column2_layout.setSpacing(2)
        self.column2_layout.addStretch()
        sf_vbox.addLayout(self.column2_layout)
        top_hbox.addWidget(sf_section, stretch=1)
        
        main_vbox.addWidget(top_row, stretch=1)
        
        # Bottom half: GND section (Aft always; Fore only for camera_flex, hidden for camera_short)
        gnd_section = QWidget()
        gnd_section.setStyleSheet("background: transparent; border-top: 2px solid #555; padding-top: 8px;")
        gnd_vbox = QVBoxLayout(gnd_section)
        gnd_vbox.setContentsMargins(0, 8, 0, 0)
        gnd_vbox.setSpacing(4)
        gnd_note = QLabel("Ground discontinuities are only detectable at the compute side pins.")
        gnd_note.setFont(get_font(9))
        gnd_note.setStyleSheet("color: #888; background: transparent; border: none;")
        gnd_note.setWordWrap(True)
        gnd_vbox.addWidget(gnd_note)
        gnd_vbox.addWidget(_make_header_row())
        self.camera_gnd_layout = QVBoxLayout()
        self.camera_gnd_layout.setContentsMargins(0, 0, 0, 0)
        self.camera_gnd_layout.setSpacing(2)
        self.camera_gnd_layout.addStretch()
        gnd_vbox.addLayout(self.camera_gnd_layout)
        main_vbox.addWidget(gnd_section, stretch=1)
        self.camera_gnd_section = gnd_section
        # Fore: hide GND section for camera_short only
        if not is_aft:
            gnd_section.setVisible(not self.flex_short_mode)
        
        self.camera_flex_main_container = main
        self.two_column_container = main
        self.channels_layout.addWidget(main)
    
    def _setup_single_column_layout(self):
        """Set up single-column layout for other tests"""
        self.pf_sf_row.setVisible(False)
        self.header_container.show()
        # Remove second set of column title bubbles from headers row (keep parented so they don't become separate windows)
        for bubble in self.header_bubbles_column2:
            self.headers_layout.removeWidget(bubble)
            bubble.setParent(self.header_container)
            bubble.hide()
        
        # Clear existing layout
        while self.channels_layout.count():
            item = self.channels_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        
        self.two_column_container = None
        self.column1_layout = None
        self.column2_layout = None
        self.camera_gnd_layout = None
        self.camera_gnd_section = None
        self.camera_flex_main_container = None
        self.channels_layout.addStretch()
    
    def _short_groups_from_channels(self, channels):
        """From short-format channels (channel + shorted_with list), return list of connected components (short groups)."""
        adj = {}
        for ch_data in channels:
            c = ch_data.get("channel")
            sw = ch_data.get("shorted_with", [])
            if c not in adj:
                adj[c] = set()
            for x in sw:
                adj[c].add(x)
                if x not in adj:
                    adj[x] = set()
                adj[x].add(c)
        visited = set()
        groups = []
        for c in adj:
            if c in visited:
                continue
            comp = set()
            stack = [c]
            while stack:
                n = stack.pop()
                if n in visited:
                    continue
                visited.add(n)
                comp.add(n)
                for nb in adj.get(n, []):
                    if nb not in visited:
                        stack.append(nb)
            if comp:
                groups.append(comp)
        return groups

    def _resistance_from_voltage(self, voltage):
        if not self.calibration_loaded:
            return None
        resistance = resistance_from_voltage(voltage, self.calibration)
        if resistance is None:
            return None
        return round(resistance, 1)

    def _store_latest_channel_reading(self, test_name, ch_num, signal, voltage, status, short_color):
        self.latest_channel_readings[(test_name, ch_num)] = {
            "signal": signal,
            "voltage": voltage,
            "status": status,
            "short_color": short_color,
        }

    def _refresh_visible_channel_resistances(self):
        for ch_num, widget in self.channel_widgets.items():
            reading = self.latest_channel_readings.get((self.current_test, ch_num))
            if not reading:
                continue
            resistance = None if "shorted with" in str(reading["status"]).lower() else self._resistance_from_voltage(reading["voltage"])
            display = self.channel_display_name(ch_num, reading.get("signal"))
            widget.update_data(
                reading.get("voltage", 0),
                reading.get("status", "UNKNOWN"),
                display,
                resistance=resistance,
                short_color=reading.get("short_color"),
                resistance_color=self._resistance_color_for_value(resistance),
                resistance_mode=self.resistance_enabled,
                resistance_ready=self.calibration_loaded,
            )

    def _request_calibration_from_device(self):
        if not (self.ser and self.ser.is_open):
            return False
        try:
            self.ser.reset_input_buffer()
        except Exception:
            pass
        for _ in range(2):
            self.send_command("get_calibration")
            deadline = time.time() + 1.5
            while time.time() < deadline:
                QApplication.processEvents()
                if self.calibration_loaded:
                    return True
                try:
                    if not self.ser.in_waiting:
                        time.sleep(0.05)
                        continue
                    line = self.ser.readline().decode(errors="ignore").strip()
                    if not line or not line.startswith("{"):
                        continue
                    data = json.loads(line)
                    if "calibration" in data:
                        incoming = data.get("calibration")
                        if isinstance(incoming, dict):
                            updated = dict(DEFAULT_CALIBRATION)
                            updated.update(incoming)
                            self.calibration = updated
                        self.calibration_loaded = bool(data.get("calibration_loaded", self.calibration_loaded))
                        return self.calibration_loaded
                except Exception:
                    pass
        return False

    def _capture_calibration_voltage(self):
        if not (self.ser and self.ser.is_open):
            return None
        self.pending_calibration_voltage = None
        try:
            self.ser.reset_input_buffer()
        except Exception:
            pass
        self.send_command("measure_calibration")
        deadline = time.time() + 1.0
        while time.time() < deadline:
            try:
                QApplication.processEvents()
                if self.pending_calibration_voltage is not None:
                    return self.pending_calibration_voltage
                if self.ser.in_waiting:
                    line = self.ser.readline().decode(errors="ignore").strip()
                    if line.startswith("{"):
                        data = json.loads(line)
                        if "calibration_measurement" in data:
                            measurement = data.get("calibration_measurement")
                            if isinstance(measurement, dict):
                                self.pending_calibration_voltage = measurement.get("voltage")
                                return self.pending_calibration_voltage
                        if "calibration" in data:
                            incoming = data.get("calibration")
                            if isinstance(incoming, dict):
                                updated = dict(DEFAULT_CALIBRATION)
                                updated.update(incoming)
                                self.calibration = updated
                            self.calibration_loaded = bool(data.get("calibration_loaded", self.calibration_loaded))
                time.sleep(0.05)
            except Exception:
                pass
        return None

    def _apply_board_type_ui(self):
        self.resistance_enabled = (self.board_type == "resistance")
        try:
            self.resistance_header_bubble.setVisible(self.resistance_enabled)
        except Exception:
            pass
        if hasattr(self, "header_bubbles_column2") and self.header_bubbles_column2:
            try:
                self.resistance_header_bubble2.setVisible(self.resistance_enabled)
            except Exception:
                pass
        show_mode_buttons = not self.resistance_enabled
        self.flex_mode_row.setVisible(show_mode_buttons and self.test_combo.currentText() in ("AoA/Pitot Test", "Hover Fore Flex Test", "Hover Aft Flex Test", "Camera Flex Test"))
        self.cdist_mode_row.setVisible(show_mode_buttons and self.test_combo.currentText() == "Compute Distro Test")
        for w in self.channel_widgets.values():
            w.set_resistance_visible(self.resistance_enabled)
        self.calibrate_btn.setVisible(self.resistance_enabled)
        self.change_board_type_btn.setText("Current Board Type: %s" % ("Resistance" if self.resistance_enabled else "Continuity / Short"))
        self.headers_widget.updateGeometry()
        self.header_container.updateGeometry()
        self.channels_widget.updateGeometry()
        self._refresh_visible_channel_resistances()

    def _update_board_type_status_label(self):
        if self.board_type != "resistance":
            return
        if self.calibration_loaded:
            self.status_label.setText("Resistance board selected. Using Pico calibration.")
            self.status_label.setStyleSheet("color: #0d8c5a;")
        else:
            self.status_label.setText("Resistance board selected. Calibration required.")
            self.status_label.setStyleSheet("color: #FED541;")

    def _check_calibration_after_board_switch(self):
        if self.board_type != "resistance":
            return
        if self._request_calibration_from_device():
            self._apply_board_type_ui()
        self._update_board_type_status_label()

    def _set_board_type(self, board_type):
        self.board_type = board_type
        self._apply_board_type_ui()
        self._update_board_type_status_label()
        if self.board_type == "resistance" and self.ser and self.ser.is_open and not self.calibration_loaded:
            QTimer.singleShot(0, self._check_calibration_after_board_switch)

    def prompt_change_board_type(self):
        choice = show_styled_choice(
            self,
            "Board Type",
            "Choose which board is connected. Resistance mode shows calibrated ohms and color-only status. Continuity/short mode keeps the default tester behavior.",
            [
                ("continuity", "Continuity / Short Board", False),
                ("resistance", "Resistance Board", False),
                ("cancel", "Cancel", False),
            ],
        )
        if choice in ("continuity", "resistance"):
            self._set_board_type(choice)

    def prompt_startup_board_type(self):
        choice = show_styled_choice(
            self,
            "Board Type",
            "Are you using the high accuracy resistance measurement board or the normal continuity / short board?",
            [
                ("continuity", "Continuity / Short Board", False),
                ("resistance", "Resistance Board", False),
            ],
        )
        self._set_board_type(choice or "continuity")

    def _resistance_reference_range(self):
        points = self.calibration.get("calibration_points", [])
        known_values = []
        if isinstance(points, list):
            for point in points:
                try:
                    known_values.append(float(point.get("known_resistance_ohms")))
                except Exception:
                    pass
        if not known_values:
            known_values = list(DEFAULT_CALIBRATION_POINTS)
        lo = min(known_values)
        hi = max(known_values)
        if hi <= lo:
            hi = lo + 1.0
        return lo, hi

    def _interp_hex(self, start_hex, end_hex, ratio):
        ratio = max(0.0, min(1.0, float(ratio)))
        start_hex = start_hex.lstrip("#")
        end_hex = end_hex.lstrip("#")
        sr, sg, sb = int(start_hex[0:2], 16), int(start_hex[2:4], 16), int(start_hex[4:6], 16)
        er, eg, eb = int(end_hex[0:2], 16), int(end_hex[2:4], 16), int(end_hex[4:6], 16)
        rr = round(sr + (er - sr) * ratio)
        rg = round(sg + (eg - sg) * ratio)
        rb = round(sb + (eb - sb) * ratio)
        return "#%02x%02x%02x" % (rr, rg, rb)

    def _resistance_color_for_value(self, resistance):
        if resistance is None:
            return None
        return "#E74C3C" if float(resistance) > 10.0 else "#27AE60"

    def calibrate_resistance_from_y15(self):
        if not (self.ser and self.ser.is_open):
            show_styled_choice(
                self,
                "Calibration",
                "Connect to the Pico first, then click Calibrate to capture pin 30 to pin 30 on the resistance board.",
                [("ok", "OK", True)],
            )
            return False

        self._request_calibration_from_device()
        captured_points = []
        for known_resistance in DEFAULT_CALIBRATION_POINTS:
            choice = show_styled_choice(
                self,
                "Capture %g Ω" % known_resistance,
                "Connect the %g Ω resistor from pin 30 to pin 30, wait for the reading to settle, then capture it." % known_resistance,
                [("capture", "Capture", True), ("cancel", "Cancel", False)],
            )
            if choice != "capture":
                return False

            measured_voltage = self._capture_calibration_voltage()
            if measured_voltage is None:
                show_styled_choice(
                    self,
                    "Calibration Error",
                    "No live reading was available for the %g Ω capture." % known_resistance,
                    [("ok", "OK", True)],
                )
                return False
            captured_points.append({
                "resistance_ohms": float(known_resistance),
                "voltage": float(measured_voltage),
            })

        try:
            self.calibration = solve_calibration_from_four_points(captured_points, self.calibration)
        except Exception as exc:
            show_styled_choice(self, "Calibration Error", str(exc), [("ok", "OK", True)])
            return False

        if self.ser and self.ser.is_open:
            self.send_command("set_calibration:%s" % json.dumps(self.calibration, separators=(",", ":")))
        self.calibration_loaded = True

        self._refresh_visible_channel_resistances()
        capture_lines = ["%g Ω capture: %.3f V" % (point["resistance_ohms"], point["voltage"]) for point in captured_points]
        show_styled_choice(
            self,
            "Calibration Saved",
            "Saved calibration to the Pico.\n\n%s\n\nSolved R1 = %.3f\nSolved R2 = %.3f" % (
                "\n".join(capture_lines),
                float(self.calibration["r1"]),
                float(self.calibration["r2"]),
            ),
            [("ok", "OK", True)],
        )
        return True

    def channel_display_name(self, ch_num, signal_name=None):
        """Return display label for a channel (signal name only)."""
        if signal_name is None:
            if self.current_test == "compute_distro":
                signal_name = self.compute_distro_signal_names.get(ch_num)
            elif self.current_test in ("aoa", "aoa_short"):
                signal_name = self.aoa_signal_names.get(ch_num)
            elif self.current_test == "hover_aft_flex":
                signal_name = self.hover_aft_flex_signal_names.get(ch_num)
            elif self.current_test == "hover_aft_short":
                signal_name = self.hover_aft_flex_signal_names.get(ch_num)
            elif self.current_test == "hover_fore_flex":
                signal_name = self.hover_fore_flex_signal_names.get(ch_num)
            elif self.current_test == "hover_fore_short":
                signal_name = self.hover_fore_flex_signal_names.get(ch_num)
            elif self.current_test == "camera_flex":
                signal_name = self.camera_flex_signal_names.get(ch_num)
            elif self.current_test == "camera_short":
                signal_name = self.camera_short_signal_names.get(ch_num)
            elif self.current_test in ("camera_aft_flex", "camera_aft_short"):
                signal_name = self.camera_aft_flex_signal_names.get(ch_num)
        return signal_name if signal_name else ("Y%d" % ch_num)

    def _current_measurement_mode(self):
        if self.board_type == "resistance":
            return "resistance"
        if self.current_test == "compute_distro":
            return "short" if self.cdist_short_mode else "continuity"
        if self.current_test in ("aoa_short", "hover_aft_short", "hover_fore_short", "camera_short", "camera_aft_short"):
            return "short"
        return "continuity"

    def _current_flex_label(self):
        if self.current_test == "compute_distro":
            return "Compute Distro"
        if self.current_test in ("aoa", "aoa_short"):
            return "AoA / Pitot"
        if self.current_test in ("hover_aft_flex", "hover_aft_short"):
            return "Hover Aft Flex"
        if self.current_test in ("hover_fore_flex", "hover_fore_short"):
            return "Hover Fore Flex"
        if self.current_test in ("camera_aft_flex", "camera_aft_short"):
            return "Camera Flex Aft"
        if self.current_test in ("camera_flex", "camera_short"):
            return "Camera Flex Fore"
        return self.test_combo.currentText()

    def _export_test_name(self):
        test_name = str(self.current_test)
        measurement_mode = self._current_measurement_mode()
        if measurement_mode == "short" and test_name.endswith("_short"):
            return test_name[:-6]
        if measurement_mode == "continuity" and test_name.endswith("_flex"):
            return test_name[:-5]
        return test_name

    def _channel_export_rows(self):
        rows = []
        current_keys = [key for key in self.latest_channel_readings.keys() if key[0] == self.current_test]
        for _, ch_num in sorted(current_keys, key=lambda item: item[1]):
            reading = self.latest_channel_readings.get((self.current_test, ch_num), {})
            signal_name = reading.get("signal") or self.channel_display_name(ch_num)
            status = reading.get("status", "UNKNOWN")
            try:
                voltage = float(reading.get("voltage", 0.0))
            except (TypeError, ValueError):
                voltage = None
            resistance = None
            if self.board_type == "resistance" and "shorted with" not in str(status).lower():
                resistance = self._resistance_from_voltage(voltage)
            short_color = reading.get("short_color")
            row = {
                "channel_number": int(ch_num),
                "channel_name": self.channel_display_name(ch_num, signal_name),
                "signal_name": signal_name,
                "voltage_v": voltage,
                "resistance_ohms": resistance,
                "short_group_color": list(short_color) if isinstance(short_color, (tuple, list)) else None,
            }
            if self.board_type == "resistance":
                status_text = str(status).strip().lower()
                if "shorted with" in status_text:
                    condition = "short"
                elif resistance is None:
                    condition = "open_circuit"
                else:
                    condition = "measured"
                row["condition"] = condition
            else:
                row["status"] = status
            rows.append(row)
        return rows

    def _build_export_payload(self):
        channels = self._channel_export_rows()
        if not channels:
            return None

        now = datetime.now().astimezone()
        measurement_mode = self._current_measurement_mode()
        export_payload = {
            "export_version": 1,
            "timestamp_iso": now.isoformat(),
            "date": now.strftime("%Y-%m-%d"),
            "time": now.strftime("%H:%M:%S"),
            "board_type": self.board_type,
            "measurement_mode": measurement_mode,
            "test_key": self.current_test,
            "test_label": self.test_combo.currentText(),
            "flex_type": self._current_flex_label(),
            "channels": channels,
        }

        if self.board_type == "resistance":
            export_payload["calibration"] = {
                "loaded": bool(self.calibration_loaded),
                "r1": self.calibration.get("r1"),
                "r2": self.calibration.get("r2"),
                "demux_r": self.calibration.get("demux_r"),
                "mux_r": self.calibration.get("mux_r"),
                "calibration_points": self.calibration.get("calibration_points", []),
            }

        if self.board_type == "resistance":
            measured_count = 0
            open_count = 0
            short_count = 0
            measured_resistances = []
            for channel in channels:
                condition = str(channel.get("condition", "")).strip().lower()
                if condition == "measured":
                    measured_count += 1
                    if channel.get("resistance_ohms") is not None:
                        measured_resistances.append(float(channel["resistance_ohms"]))
                elif condition == "open_circuit":
                    open_count += 1
                elif condition == "short":
                    short_count += 1
            export_payload["summary"] = {
                "channel_count": len(channels),
                "measured_count": measured_count,
                "open_count": open_count,
                "short_count": short_count,
                "min_resistance_ohms": min(measured_resistances) if measured_resistances else None,
                "max_resistance_ohms": max(measured_resistances) if measured_resistances else None,
            }
        else:
            pass_count = 0
            fail_count = 0
            short_count = 0
            for channel in channels:
                status_text = str(channel.get("status", "")).strip().lower()
                if status_text == "pass":
                    pass_count += 1
                elif status_text == "fail":
                    fail_count += 1
                if "shorted with" in status_text:
                    short_count += 1
            export_payload["summary"] = {
                "channel_count": len(channels),
                "pass_count": pass_count,
                "fail_count": fail_count,
                "short_count": short_count,
            }
        return export_payload

    def export_results(self):
        payload = self._build_export_payload()
        if not payload:
            show_styled_choice(
                self,
                "Export Error",
                "No test results are available yet. Run a test first, then export the current results.",
                [("ok", "OK", True)],
            )
            return

        default_name = "%s_%s_%s_%s.json" % (
            payload["date"].replace("-", ""),
            payload["time"].replace(":", ""),
            payload["measurement_mode"],
            self._export_test_name(),
        )
        default_path = os.path.join(self.last_export_dir, default_name)
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Test Results",
            default_path,
            "JSON Files (*.json)"
        )
        if not file_path:
            return
        if not file_path.lower().endswith(".json"):
            file_path += ".json"

        try:
            with open(file_path, "w", encoding="utf-8") as export_file:
                json.dump(payload, export_file, indent=2)
            saved_dir = os.path.dirname(file_path)
            if saved_dir:
                self.last_export_dir = saved_dir
        except Exception as exc:
            show_styled_choice(
                self,
                "Export Error",
                "Could not save the export file.\n\n%s" % exc,
                [("ok", "OK", True)],
            )
            return

        show_styled_choice(
            self,
            "Export Saved",
            "Saved test results to:\n\n%s" % file_path,
            [("ok", "OK", True)],
        )
    
    def ensure_channel_display(self, ch_num, signal_name=None):
        """Ensure a channel display widget exists for the given channel number"""
        display = self.channel_display_name(ch_num, signal_name)
        if ch_num not in self.channel_widgets:
            channel_widget = ChannelWidget(ch_num)
            channel_widget.channel_label.setText(display)
            
            # Check if we're using two-column layout (compute distro or camera flex)
            if self.column1_layout is not None and self.column2_layout is not None:
                if self.current_test == "camera_short":
                    # Camera Short (Fore): 12 channels — PF col1 (1-6), SF col2 (7-12), no GND
                    if ch_num in self.camera_short_pf_channels:
                        insert_pos = 0
                        for existing_ch in sorted([c for c in self.channel_widgets.keys() if c in self.camera_short_pf_channels]):
                            if existing_ch < ch_num:
                                insert_pos += 1
                            else:
                                break
                        self.column1_layout.insertWidget(insert_pos, channel_widget)
                    else:
                        insert_pos = 0
                        for existing_ch in sorted([c for c in self.channel_widgets.keys() if c in self.camera_short_sf_channels]):
                            if existing_ch < ch_num:
                                insert_pos += 1
                            else:
                                break
                        self.column2_layout.insertWidget(insert_pos, channel_widget)
                elif self.current_test == "camera_flex":
                    # Camera Flex Fore: PF col1, SF col2; GND only if Aft layout (camera_gnd_layout set)
                    if ch_num in self.camera_flex_gnd_channels and self.camera_gnd_layout is not None:
                        insert_pos = 0
                        for existing_ch in sorted([c for c in self.channel_widgets.keys() if c in self.camera_flex_gnd_channels]):
                            if existing_ch < ch_num:
                                insert_pos += 1
                            else:
                                break
                        self.camera_gnd_layout.insertWidget(insert_pos, channel_widget)
                    elif ch_num in self.camera_flex_pf_channels:
                        insert_pos = 0
                        for existing_ch in sorted([c for c in self.channel_widgets.keys() if c in self.camera_flex_pf_channels]):
                            if existing_ch < ch_num:
                                insert_pos += 1
                            else:
                                break
                        self.column1_layout.insertWidget(insert_pos, channel_widget)
                    else:
                        insert_pos = 0
                        for existing_ch in sorted([c for c in self.channel_widgets.keys() if c in self.camera_flex_sf_channels]):
                            if existing_ch < ch_num:
                                insert_pos += 1
                            else:
                                break
                        self.column2_layout.insertWidget(insert_pos, channel_widget)
                elif self.current_test in ("camera_aft_flex", "camera_aft_short") and self.camera_gnd_layout is not None:
                    # Camera Aft: PA col1, SA col2, GND bottom
                    if ch_num in self.camera_aft_flex_gnd_channels:
                        insert_pos = 0
                        for existing_ch in sorted([c for c in self.channel_widgets.keys() if c in self.camera_aft_flex_gnd_channels]):
                            if existing_ch < ch_num:
                                insert_pos += 1
                            else:
                                break
                        self.camera_gnd_layout.insertWidget(insert_pos, channel_widget)
                    elif ch_num in self.camera_aft_flex_pa_channels:
                        insert_pos = 0
                        for existing_ch in sorted([c for c in self.channel_widgets.keys() if c in self.camera_aft_flex_pa_channels]):
                            if existing_ch < ch_num:
                                insert_pos += 1
                            else:
                                break
                        self.column1_layout.insertWidget(insert_pos, channel_widget)
                    else:
                        insert_pos = 0
                        for existing_ch in sorted([c for c in self.channel_widgets.keys() if c in self.camera_aft_flex_sa_channels]):
                            if existing_ch < ch_num:
                                insert_pos += 1
                            else:
                                break
                        self.column2_layout.insertWidget(insert_pos, channel_widget)
                else:
                    # Compute Distro: C1-C15 col1, C16-C30 col2
                    split = 15
                    if ch_num <= split:
                        insert_pos = 0
                        for existing_ch in sorted([c for c in self.channel_widgets.keys() if c <= split]):
                            if existing_ch < ch_num:
                                insert_pos += 1
                            else:
                                break
                        self.column1_layout.insertWidget(insert_pos, channel_widget)
                    else:
                        insert_pos = 0
                        for existing_ch in sorted([c for c in self.channel_widgets.keys() if c > split]):
                            if existing_ch < ch_num:
                                insert_pos += 1
                            else:
                                break
                        self.column2_layout.insertWidget(insert_pos, channel_widget)
            else:
                # Single-column layout (Hover Fore Flex: GNDs at bottom)
                if self.current_test == "hover_fore_flex":
                    order = self.hover_fore_flex_channel_order
                    idx = order.index(ch_num)
                    insert_pos = 0
                    for existing_ch in self.channel_widgets.keys():
                        if order.index(existing_ch) < idx:
                            insert_pos += 1
                    self.channels_layout.insertWidget(insert_pos, channel_widget)
                else:
                    insert_pos = 0
                    for existing_ch in sorted(self.channel_widgets.keys()):
                        if existing_ch < ch_num:
                            insert_pos += 1
                        else:
                            break
                    self.channels_layout.insertWidget(insert_pos, channel_widget)
            
            self.channel_widgets[ch_num] = channel_widget
        else:
            # Update display (name + pin) if widget already exists
            self.channel_widgets[ch_num].channel_label.setText(display)
    
    def remove_all_channel_displays(self):
        """Remove all channel displays"""
        for ch_num in list(self.channel_widgets.keys()):
            widget = self.channel_widgets[ch_num]
            # Remove from appropriate layout
            if self.column1_layout:
                self.column1_layout.removeWidget(widget)
            if self.column2_layout:
                self.column2_layout.removeWidget(widget)
            if self.camera_gnd_layout:
                self.camera_gnd_layout.removeWidget(widget)
            self.channels_layout.removeWidget(widget)  # Safe to call even if not in this layout
            widget.deleteLater()
        self.channel_widgets.clear()
    
    def reorder_channels(self):
        """Reorder channel widgets in the layout to be sorted by channel number"""
        # Get all widgets in sorted order
        sorted_channels = sorted(self.channel_widgets.keys())
        
        # Remove all widgets from layout
        for ch_num in sorted_channels:
            widget = self.channel_widgets[ch_num]
            self.channels_layout.removeWidget(widget)
        
        # Re-add them in sorted order
        for ch_num in sorted_channels:
            widget = self.channel_widgets[ch_num]
            self.channels_layout.insertWidget(self.channels_layout.count() - 1, widget)
    
    def auto_detect_serial(self, baud=115200, keywords=("Arduino", "Teensy", "CH340", "Silicon", "USB Serial", "USB")):
        """Auto-detect and connect to serial port"""
        ports = list(serial.tools.list_ports.comports())
        for p in ports:
            desc = p.description.lower()
            if any(k.lower() in desc for k in keywords):
                try:
                    ser = serial.Serial(p.device, baud, timeout=0.1)
                    print("Connected to %s (%s)" % (p.device, p.description))
                    return ser
                except Exception as e:
                    print("Failed to open %s: %s" % (p.device, e))
        if not ports:
            print("No COM ports found.")
        else:
            print("No matching device found. Available ports:")
            for p in ports:
                print(" - %s: %s" % (p.device, p.description))
        return None
    
    def send_command(self, command):
        """Send a command to the Pico via serial"""
        if self.ser and self.ser.is_open:
            try:
                cmd_bytes = (command + "\n").encode('utf-8')
                self.ser.write(cmd_bytes)
                print("Sent command:", command)
                time.sleep(0.1)
            except Exception as e:
                print("Error sending command:", e)
    
    def update_gui(self):
        """Update GUI with JSON data from serial"""
        if not self.updating or not self.ser:
            return
        
        # Check if serial port is still open
        if not self.ser.is_open:
            print("Serial port is closed. Attempting to reconnect...")
            try:
                self.ser.close()
            except:
                pass
            # Stop the test and enable Start button
            self.updating = False
            self.start_button.setEnabled(True)
            self.stop_button.setEnabled(False)
            self.ser = self.auto_detect_serial(BAUD_RATE)
            if not self.ser:
                self.status_label.setText("Device disconnected - Click Start to reconnect")
                self.status_label.setStyleSheet("color: #FED541;")
                return
            else:
                # Reconnected - keep Start button enabled
                self.status_label.setText("Device reconnected - Click Start to resume")
                self.status_label.setStyleSheet("color: #0d8c5a;")
                return
        
        try:
            # Read all available lines from serial buffer
            while self.ser.in_waiting:
                line = self.ser.readline().decode(errors="ignore").strip()
                if not line:
                    continue
                
                # Look for JSON data
                if line.startswith("{"):
                    try:
                        data = json.loads(line)
                    except json.JSONDecodeError:
                        print("Skipping invalid JSON:", line)
                        continue
                    if "calibration" in data:
                        incoming = data.get("calibration")
                        if isinstance(incoming, dict):
                            updated = dict(DEFAULT_CALIBRATION)
                            updated.update(incoming)
                            self.calibration = updated
                        self.calibration_loaded = bool(data.get("calibration_loaded", self.calibration_loaded))
                        if self.resistance_enabled:
                            self._apply_board_type_ui()
                            self._refresh_visible_channel_resistances()
                        continue
                    if "calibration_measurement" in data:
                        measurement = data.get("calibration_measurement")
                        if isinstance(measurement, dict):
                            self.pending_calibration_voltage = measurement.get("voltage")
                        continue
                    try:
                        self.last_json_time = time.time()
                        self.json_indicator_label.setText("Receiving JSON: Yes")
                        self.json_indicator_label.setStyleSheet("color: #0d8c5a;")
                        channels = data.get("channels", [])
                        channels = sorted(channels, key=lambda x: x.get("channel", 0))
                        is_short_format = channels and isinstance(channels[0], dict) and "shorted_with" in channels[0]
                        short_groups = self._short_groups_from_channels(channels) if is_short_format else []
                        ch_to_group_index = {}
                        ch_to_others = {}
                        for gidx, group in enumerate(short_groups):
                            for ch in group:
                                ch_to_group_index[ch] = gidx
                                ch_to_others[ch] = sorted(group - {ch})
                        for ch_data in channels:
                            if not isinstance(ch_data, dict):
                                continue
                            ch_num = ch_data.get("channel", 0)
                            if ch_num not in self.valid_channels:
                                continue
                            signal = ch_data.get("signal", None)
                            short_color = None
                            if is_short_format:
                                shorted_with = ch_data.get("shorted_with", [])
                                voltage = 0
                                if not shorted_with:
                                    status = "PASS"
                                else:
                                    others = ch_to_others.get(ch_num, sorted(set(shorted_with)))
                                    status = "shorted with " + ", ".join(self.channel_display_name(c) for c in others)
                                    if ch_num in ch_to_group_index:
                                        bg, fg = SHORT_GROUP_COLORS[ch_to_group_index[ch_num] % len(SHORT_GROUP_COLORS)]
                                        short_color = (bg, fg)
                                resistance = None
                            else:
                                voltage = ch_data.get("voltage", 0)
                                status = ch_data.get("status", "UNKNOWN")
                                resistance = self._resistance_from_voltage(voltage)
                            self._store_latest_channel_reading(self.current_test, ch_num, signal, voltage, status, short_color)
                            self.ensure_channel_display(ch_num, signal)
                            if ch_num in self.channel_widgets:
                                display = self.channel_display_name(ch_num, signal or (self.compute_distro_signal_names.get(ch_num) if self.current_test == "compute_distro" else self.aoa_signal_names.get(ch_num) if self.current_test in ("aoa", "aoa_short") else self.hover_aft_flex_signal_names.get(ch_num) if self.current_test in ("hover_aft_flex", "hover_aft_short") else self.hover_fore_flex_signal_names.get(ch_num) if self.current_test in ("hover_fore_flex", "hover_fore_short") else self.camera_short_signal_names.get(ch_num) if self.current_test == "camera_short" else self.camera_flex_signal_names.get(ch_num) if self.current_test == "camera_flex" else self.camera_aft_flex_signal_names.get(ch_num) if self.current_test in ("camera_aft_flex", "camera_aft_short") else None))
                                display_status = "not testable yet" if status == "N/A" else status
                                self.channel_widgets[ch_num].update_data(
                                    voltage,
                                    display_status,
                                    display,
                                    resistance=resistance,
                                    short_color=short_color,
                                    resistance_color=self._resistance_color_for_value(resistance),
                                    resistance_mode=self.resistance_enabled,
                                    resistance_ready=self.calibration_loaded,
                                )
                    except Exception as e:
                        print("GUI update error processing JSON:", e)
                        continue
                else:
                    # Print non-JSON lines for debugging (like "Compute Distro test started")
                    print("Serial output:", line)
        
        except (serial.SerialException, PermissionError, OSError) as e:
            # Handle serial port disconnection errors
            print(f"Serial port error (device may be disconnected): {e}")
            try:
                if self.ser and self.ser.is_open:
                    self.ser.close()
            except:
                pass
            self.ser = None
            # Stop the test and enable Start button
            self.updating = False
            self.start_button.setEnabled(True)
            self.stop_button.setEnabled(False)
            self.status_label.setText("Device disconnected - Click Start to reconnect")
            self.status_label.setStyleSheet("color: #FED541;")
            # Start monitoring for reconnection
            if not self.reconnect_timer.isActive():
                self.reconnect_timer.start(2000)  # Check every 2 seconds
        
        except Exception as e:
            # Catch any other unexpected errors
            print(f"GUI update error: {e}")
    
    def _update_json_indicator(self):
        """Update the temporary JSON receive indicator and device connection indicator."""
        # Device connection indicator - actively monitor for connection
        # Check if current connection is still valid
        if self.ser and self.ser.is_open:
            try:
                # Try to check if port is still valid (this will raise exception if disconnected)
                _ = self.ser.in_waiting
                self.device_indicator_label.setText("Device: Connected")
                self.device_indicator_label.setStyleSheet("color: #0d8c5a;")
            except (serial.SerialException, OSError, AttributeError):
                # Port was disconnected - close it
                try:
                    self.ser.close()
                except:
                    pass
                self.ser = None
                self.device_indicator_label.setText("Device: Disconnected")
                self.device_indicator_label.setStyleSheet("color: #F73B30;")
        else:
            # No connection - try to auto-detect (but don't interfere if test is running)
            if not self.updating:  # Only auto-detect when not running a test
                detected_ser = self.auto_detect_serial(BAUD_RATE)
                if detected_ser:
                    self.ser = detected_ser
                    self.device_indicator_label.setText("Device: Connected")
                    self.device_indicator_label.setStyleSheet("color: #0d8c5a;")
                    self.status_label.setText("Device connected")
                    self.status_label.setStyleSheet("color: #0d8c5a;")
                else:
                    self.device_indicator_label.setText("Device: Disconnected")
                    self.device_indicator_label.setStyleSheet("color: #F73B30;")
            else:
                # Test is running but no connection - show disconnected
                self.device_indicator_label.setText("Device: Disconnected")
                self.device_indicator_label.setStyleSheet("color: #F73B30;")
        
        # JSON receive indicator
        if not self.updating or not self.ser:
            self.json_indicator_label.setText("Receiving JSON: —")
            self.json_indicator_label.setStyleSheet("color: #888;")
            return
        elapsed = time.time() - self.last_json_time
        if elapsed > 2.0:
            self.json_indicator_label.setText("Receiving JSON: No (%.1fs ago)" % elapsed)
            self.json_indicator_label.setStyleSheet("color: #F73B30;")
        else:
            self.json_indicator_label.setText("Receiving JSON: Yes")
            self.json_indicator_label.setStyleSheet("color: #0d8c5a;")
    
    def check_for_reconnection(self):
        """Check if device has been reconnected when it was previously disconnected"""
        # Only check if we're not currently connected and not running a test
        if self.ser and self.ser.is_open:
            return
        
        # Try to reconnect
        self.ser = self.auto_detect_serial(BAUD_RATE)
        if self.ser:
            self.status_label.setText("Device connected")
            self.status_label.setStyleSheet("color: #0d8c5a;")
            self.reconnect_timer.stop()  # Stop monitoring since we're connected
            print("Device automatically reconnected!")
    
    def on_test_change(self, selected_text):
        """Handle test selection dropdown change"""
        # Determine which channels to show
        if selected_text == "AoA/Pitot Test":
            self.current_test = "aoa_short" if self.flex_short_mode else "aoa"
            channels_to_show = [10, 11, 12, 13, 14, 15]
            signal_names = self.aoa_signal_names
        elif selected_text == "Compute Distro Test":
            self.current_test = "compute_distro"
            channels_to_show = list(range(1, 31))  # C1-C30
            signal_names = self.compute_distro_signal_names
        elif selected_text == "Hover Aft Flex Test":
            self.current_test = "hover_aft_short" if self.flex_short_mode else "hover_aft_flex"
            channels_to_show = list(range(1, 11))  # 10 channels
            signal_names = self.hover_aft_flex_signal_names
        elif selected_text == "Hover Fore Flex Test":
            self.current_test = "hover_fore_short" if self.flex_short_mode else "hover_fore_flex"
            channels_to_show = list(range(1, 6))  # 5 channels
            signal_names = self.hover_fore_flex_signal_names
        elif selected_text == "Camera Flex Test":
            if self.camera_aft_mode:
                self.current_test = "camera_aft_short" if self.flex_short_mode else "camera_aft_flex"
                signal_names = self.camera_aft_flex_signal_names
                channels_to_show = list(range(1, 21))  # 20 channels (Aft)
            else:
                self.current_test = "camera_short" if self.flex_short_mode else "camera_flex"
                signal_names = self.camera_short_signal_names if self.flex_short_mode else self.camera_flex_signal_names
                # Fore: camera_flex = 20 channels (with GND); camera_short = 12 channels (no GND)
                if self.flex_short_mode:
                    channels_to_show = list(range(1, 13))  # camera_short 1-12
                else:
                    channels_to_show = list(range(1, 21))  # camera_flex 20 channels including GND
        else:
            return
        
        # Update valid channels FIRST
        self.valid_channels = channels_to_show
        
        print("Switching to %s - removing all channels, then showing: %s" % (selected_text, channels_to_show))
        
        # Remove ALL channels first
        self.remove_all_channel_displays()
        
        # Set up layout based on test type
        if selected_text in ["Compute Distro Test", "Camera Flex Test"]:
            self._setup_two_column_layout()
        else:
            self._setup_single_column_layout()
        
        # Recreate only the channels for the current test IN SORTED ORDER
        sorted_channels = sorted(channels_to_show)
        for ch_num in sorted_channels:
            # Use signal name if available (for AoA test)
            signal_name = signal_names.get(ch_num) if signal_names else None
            self.ensure_channel_display(ch_num, signal_name)
            print("Created channel display for: %d" % ch_num)
        
        # Insert note under CHASSIS channel for Hover Aft Flex only
        # Compute Distro: show Continuity/Short row and apply voltage visibility for short mode
        if selected_text == "Compute Distro Test":
            self.cdist_mode_row.setVisible(True)
            self.flex_mode_row.setVisible(False)
            self.camera_fore_aft_row.setVisible(False)
            self.voltage_header_bubble.setVisible(not self.cdist_short_mode)
            if hasattr(self, "header_bubbles_column2") and self.header_bubbles_column2:
                self.header_bubbles_column2[1].setVisible(not self.cdist_short_mode)
            for w in self.channel_widgets.values():
                w.set_voltage_visible(not self.cdist_short_mode)
        elif selected_text in ("AoA/Pitot Test", "Hover Fore Flex Test", "Hover Aft Flex Test", "Camera Flex Test"):
            self.cdist_mode_row.setVisible(False)
            self.flex_mode_row.setVisible(True)
            self.flex_continuity_btn.setChecked(not self.flex_short_mode)
            self.flex_short_btn.setChecked(self.flex_short_mode)
            self.voltage_header_bubble.setVisible(not self.flex_short_mode)
            if hasattr(self, "header_bubbles_column2") and self.header_bubbles_column2:
                self.header_bubbles_column2[1].setVisible(not self.flex_short_mode)
            for w in self.channel_widgets.values():
                w.set_voltage_visible(not self.flex_short_mode)
            if selected_text == "Camera Flex Test":
                self.camera_fore_aft_row.setVisible(True)
                self.camera_fore_btn.setChecked(not self.camera_aft_mode)
                self.camera_aft_btn.setChecked(self.camera_aft_mode)
            else:
                self.camera_fore_aft_row.setVisible(False)
        else:
            self.cdist_mode_row.setVisible(False)
            self.flex_mode_row.setVisible(False)
            self.camera_fore_aft_row.setVisible(False)

        self._apply_board_type_ui()
        self._update_camera_short_alias_warning()

        # Send command to Pico if connected and running
        # Note: If test is running, sending a new test command will switch the test
        # The Pico's main.py will handle stopping the old test and starting the new one
        if self.ser and self.ser.is_open and self.updating:
            print("Switching test while running - sending command: test:%s" % self.current_test)
            print("New valid_channels: %s" % self.valid_channels)
            # Update status label to show the new test name
            self.status_label.setText("Running %s..." % selected_text)
            self.status_label.setStyleSheet("color: #FED541;")
            self.send_command("test:%s" % self.current_test)
            if selected_text == "Compute Distro Test":
                self.send_command("mode:%s" % ("short" if self.cdist_short_mode else "continuity"))
            # Give the Pico a moment to switch tests
            time.sleep(0.2)
        else:
            print("Test change: not running, so not sending command (test will start when Start is clicked)")

    def _update_camera_short_alias_warning(self):
        """Show warning only for Camera Fore + Short mode."""
        show_warning = (
            self.test_combo.currentText() == "Camera Flex Test"
            and (not self.camera_aft_mode)
            and self.flex_short_mode
        )
        self.camera_short_alias_warning.setVisible(show_warning)
    
    def _set_flex_mode(self, mode):
        """Switch between Continuity and Short for AoA, Camera, Hover Fore, or Hover Aft."""
        self.flex_short_mode = (mode == "short")
        self.flex_continuity_btn.setChecked(mode == "continuity")
        self.flex_short_btn.setChecked(mode == "short")
        selected = self.test_combo.currentText()
        if selected == "AoA/Pitot Test":
            self.current_test = "aoa_short" if self.flex_short_mode else "aoa"
        elif selected == "Hover Fore Flex Test":
            self.current_test = "hover_fore_short" if self.flex_short_mode else "hover_fore_flex"
        elif selected == "Hover Aft Flex Test":
            self.current_test = "hover_aft_short" if self.flex_short_mode else "hover_aft_flex"
        elif selected == "Camera Flex Test":
            if self.camera_aft_mode:
                self.current_test = "camera_aft_short" if self.flex_short_mode else "camera_aft_flex"
            else:
                self.current_test = "camera_short" if self.flex_short_mode else "camera_flex"
            # Rebuild layout so GND section hides for camera_short and channel count (12 vs 20) updates immediately
            self.on_test_change("Camera Flex Test")
            return  # on_test_change already updated visibility and sends command if running
        else:
            return
        self.voltage_header_bubble.setVisible(not self.flex_short_mode)
        if hasattr(self, "header_bubbles_column2") and self.header_bubbles_column2:
            self.header_bubbles_column2[1].setVisible(not self.flex_short_mode)
        for w in self.channel_widgets.values():
            w.set_voltage_visible(not self.flex_short_mode)
        if self.ser and self.ser.is_open and self.updating:
            self.send_command("test:%s" % self.current_test)
            time.sleep(0.2)

    def _set_camera_fore_aft(self, mode):
        """Switch between Fore (P52A) and Aft (P52B) for Camera Flex Test."""
        if mode == "aft" and not self.camera_aft_enabled:
            self.camera_aft_mode = False
            self.camera_fore_btn.setChecked(True)
            self.camera_aft_btn.setChecked(False)
            QToolTip.showText(self.camera_aft_btn.mapToGlobal(self.camera_aft_btn.rect().bottomLeft()),
                              self.camera_aft_under_dev_msg,
                              self.camera_aft_btn)
            return
        self.camera_aft_mode = (mode == "aft")
        self.camera_fore_btn.setChecked(mode == "fore")
        self.camera_aft_btn.setChecked(mode == "aft")
        if self.test_combo.currentText() != "Camera Flex Test":
            return
        self.on_test_change("Camera Flex Test")

    def start_test(self):
        """Start the test"""
        if not self.ser:
            self.ser = self.auto_detect_serial(BAUD_RATE)
            if not self.ser:
                self.status_label.setText("Error: Could not connect to device")
                self.status_label.setStyleSheet("color: #FED541;")
                return
        
        # Send test command based on dropdown selection (flex tests use Continuity/Short mode)
        selected = self.test_combo.currentText()
        if selected == "AoA/Pitot Test":
            self.current_test = "aoa_short" if self.flex_short_mode else "aoa"
        elif selected == "Compute Distro Test":
            self.current_test = "compute_distro"
        elif selected == "Hover Aft Flex Test":
            self.current_test = "hover_aft_short" if self.flex_short_mode else "hover_aft_flex"
        elif selected == "Hover Fore Flex Test":
            self.current_test = "hover_fore_short" if self.flex_short_mode else "hover_fore_flex"
        elif selected == "Camera Flex Test":
            if self.camera_aft_mode:
                self.current_test = "camera_aft_short" if self.flex_short_mode else "camera_aft_flex"
            else:
                self.current_test = "camera_short" if self.flex_short_mode else "camera_flex"
        
        self.send_command("test:%s" % self.current_test)
        if self.current_test == "compute_distro":
            self.send_command("mode:%s" % ("short" if self.cdist_short_mode else "continuity"))
        if self.board_type == "resistance":
            self._request_calibration_from_device()
        
        self.updating = True
        self.status_label.setText("Running %s..." % selected)
        self.status_label.setStyleSheet("color: #FED541;")
        self.start_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        self.update_timer.start(UPDATE_INTERVAL_MS)
        # Stop reconnection monitoring if it was running
        if self.reconnect_timer.isActive():
            self.reconnect_timer.stop()
    
    def stop_test(self):
        """Stop the test and reset all channels"""
        self.updating = False
        self.status_label.setText("Stopped")
        self.status_label.setStyleSheet("color: #F73B30;")
        self.start_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        self.update_timer.stop()
        
        # Reset all channel displays (clear voltage and status)
        for ch_num in self.channel_widgets:
            self.channel_widgets[ch_num].reset()

def main():
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())

if __name__ == "__main__":
    main()
