from kivy.app import App
from kivy.core.window import Window
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label
from kivy.uix.image import Image
from tkinter import filedialog, Tk
from kivy.core.image import Image as CoreImage


class DragDropWidget(BoxLayout):
    def __init__(self, on_file=None, **kwargs):
        super(DragDropWidget, self).__init__(**kwargs)

        self.on_file = on_file

        self.drop_area = Label(
            text="Drop image here",
            size_hint=(1, None),
            pos_hint={"top": 1},  # Align to the top
            color=(0, 1, 1, 1),
        )
        self.orientation = "vertical"
        self.add_widget(self.drop_area)
        self.image = None  # Initialize the image widget but don't add it yet

        # Bind to the on_drop_file event of the window
        Window.bind(on_drop_file=self.on_drop_file)


    def on_touch_down(self, touch):
        # Check if the touch is within the bounds of the drop area and if it's a single click
        if self.drop_area.collide_point(*touch.pos) and not (
            touch.is_double_tap or touch.is_triple_tap or touch.is_mouse_scrolling
        ):
            self.open_file_dialog()
        return super(DragDropWidget, self).on_touch_down(touch)

    def on_drop_file(self, window, file_path, *args):
        self.display_image(file_path.decode("utf-8"))

        if self.on_file:
            self.on_file(file_path)


    def display_image(self, file_path):
        app = App.get_running_app()  # Get the instance of the running app

        if not self.image:
            self.image = Image(size_hint=(1, 0.9))
            self.add_widget(self.image)
        self.image.source = file_path

        # Load the image to get its size
        core_image = CoreImage(file_path)

        img_width, img_height = core_image.size

        # Use stored screen dimensions
        max_width = app.screen_width * 0.25
        max_height = app.screen_height * 0.7

        # Set window size to the smaller of the image size and maximum allowable size
        new_width = min(img_width, max_width)
        new_height = min(img_height, max_height)
        Window.size = (new_width, new_height)

    def open_file_dialog(self):
        root = Tk()
        root.withdraw()
        file_path = filedialog.askopenfilename(
            filetypes=[("Image Files", "*.png;*.jpg;*.jpeg;*.bmp")]
        )
        if file_path:
            self.display_image(file_path)
            if self.on_file:
                self.on_file(file_path)
        root.destroy()
