import sys

from PySide6.QtWidgets import QApplication

from desktop.windows.main_window import MainWindow

STYLE = """
QWidget { background: #111827; color: #e5e7eb; font: 14px 'Segoe UI'; }
QLineEdit, QSpinBox, QComboBox, QTextEdit { background: #1f2937; border: 1px solid #374151; border-radius: 5px; padding: 7px; }
QPushButton { background: #24364b; border: 1px solid #3b526d; border-radius: 5px; padding: 9px 15px; }
QPushButton:hover { background: #315272; }
QPushButton:disabled { color: #6b7280; }
QListWidget { background: #172132; border: none; padding: 8px; }
QListWidget::item { background: #202e42; padding: 14px; margin-bottom: 7px; border-radius: 5px; }
QListWidget::item:selected { background: #2b5175; }
QHeaderView::section { background: #202e42; padding: 10px; border: none; }
QTableView { gridline-color: #27364a; alternate-background-color: #172132; }
QLabel#pageTitle { font-size: 28px; font-weight: bold; padding: 16px; }
QLabel#columnTitle { font-weight: bold; padding: 10px; color: #9dc4ed; }
QTabBar::tab { padding: 10px 20px; background: #202e42; }
QTabBar::tab:selected { background: #315272; }
"""


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setStyleSheet(STYLE)
    window = MainWindow()
    if window.login():
        window.show()
        sys.exit(app.exec())


if __name__ == "__main__":
    main()
