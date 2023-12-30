from kivy.app import App
from kivy.core.window import Window
from kivy.uix.boxlayout import BoxLayout
from gui.inputwidget import InputWidget
from gui.dragdropwidget import DragDropWidget
from modules import SD_Api_Handler


# [Rest of the MyApp class code]
class PayloadManager(App):

    def build(self):
        self.title = "Payload Manager"

        def on_window_draw(*args):
            # Store the screen size in the app instance
            self.screen_width, self.screen_height = Window.size
            Window.unbind(on_draw=on_window_draw)  # Unbind to avoid repeated calls

        def resize(*args):
            self.screen_width, self.screen_height = Window.size
            Window.size = (600, 900)  # Restore to 800x600 size
            Window.unbind(on_draw=resize)

        Window.maximize()
        
        Window.bind(on_draw=on_window_draw)
        self.screen_width, self.screen_height = Window.size
        
        Window.bind(on_draw=resize)

        Window.minimum_width, Window.minimum_height = (
            self.screen_width * 0.25,
            self.screen_height * 0.60,
        )

        drag_drop_widget = DragDropWidget(
            size_hint=(0.8, 0.4),
            pos_hint={"center_x": 0.5, "center_y": 0.5},
        )

        input_widget = InputWidget(
            size_hint=(0.8, 0.4), pos_hint={"center_x": 0.5, "center_y": 0.5}
        )

        MainLayout = BoxLayout(
            orientation="vertical",
            pos_hint={"center_x": 0.5, "center_y": 0.5},
        )

        MainLayout.add_widget(drag_drop_widget)
        MainLayout.add_widget(input_widget)

        return MainLayout


if __name__ == "__main__":
    PayloadManager().run()
