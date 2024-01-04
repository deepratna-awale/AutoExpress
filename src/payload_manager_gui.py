from kivy import Config

Config.set("graphics", "minimum_width", "600")
Config.set("graphics", "minimum_height", "900")

from kivy.app import App
from kivy.core.window import Window
from kivy.uix.boxlayout import BoxLayout
from gui.inputwidget import InputWidget
from gui.dragdropwidget import DragDropWidget
from kivy.uix.button import Button


class PayloadManager(App):
    def on_file(self, file_path):
        # This method is called when a file is dropped
        self.input_widget.set_file_path(file_path)

    def build(self):
        self.title = "Payload Manager"

        def on_window_draw(*args):
            # Store the screen size in the app instance
            self.screen_width, self.screen_height = Window.size
            Window.unbind(on_draw=on_window_draw)  # Unbind to avoid repeated calls

        def resize(*args):
            self.screen_width, self.screen_height = Window.size
            Window.size = (800, 900)
            Window.unbind(on_draw=resize)

        Window.maximize()

        Window.bind(on_draw=on_window_draw)
        self.screen_width, self.screen_height = Window.size
        Window.bind(on_draw=resize)

        self.drag_drop_widget = DragDropWidget(
            on_file=self.on_file,
            size_hint=(0.8, 0.4),
            pos_hint={"center_x": 0.5, "center_y": 0.5},
        )

        self.input_widget = InputWidget(
            size_hint=(0.8, 0.6),
            pos_hint={"center_x": 0.5, "center_y": 0.5},
        )

        MainLayout = BoxLayout(
            orientation="vertical", spacing= 20
        )

        MainLayout.add_widget(self.drag_drop_widget)
        MainLayout.add_widget(self.input_widget)

        return MainLayout


if __name__ == "__main__":
    PayloadManager().run()
