from kivy.app import App
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.textinput import TextInput
from kivy.core.window import Window
import threading
from modules import background_remover
import tkinter as tk
from tkinter import filedialog
import pathlib


# Forcing dark mode
Window.clearcolor = (0.1, 0.1, 0.1, 1)
Window.size = (800, 200)


def ask_directory_path():
    root = tk.Tk()
    root.withdraw()  # Hide the main window
    directory_path = filedialog.askdirectory()
    root.destroy()
    return directory_path


class RowLayout(BoxLayout):
    def __init__(self, label_text, **kwargs):
        super(RowLayout, self).__init__(**kwargs)
        self.orientation = "horizontal"
        self.spacing = 5
        self.padding = [2, 0]
        self.size_hint = (1, 0.33)

        # Label
        self.add_widget(
            Label(text=label_text, color=(1, 1, 1, 1), size_hint=(0.2, 0.5))
        )

        # Text Input
        self.text_input = TextInput(
            multiline=False,
            size_hint=(0.7, 0.5),
            background_color=(0.3, 0.3, 0.3, 1),
            foreground_color=(1, 1, 1, 1),
        )
        self.add_widget(self.text_input)

        # Browse Button
        browse_button = Button(text="Browse", size_hint=(0.1, 0.5))
        browse_button.bind(on_release=self.open_file_dialog)

        self.add_widget(browse_button)

    def open_file_dialog(self, instance):
        directory = ask_directory_path()
        if directory:
            self.text_input.text = directory


class RootWidget(BoxLayout):
    def __init__(self, **kwargs):
        super(RootWidget, self).__init__(**kwargs)
        self.orientation = "vertical"

        self.spacing = 10

        # Input Path
        self.input_layout = RowLayout("Input Directory:")
        self.add_widget(self.input_layout)

        # Output Path
        self.output_layout = RowLayout("Output Directory:")
        self.add_widget(self.output_layout)

        # Start Button
        self.start_button = Button(
            text="Remove Background",
            size_hint_y=0.33,
            height=50,
            background_color=(0.56, 0.93, 0.56, 1),
        )
        self.start_button.bind(on_release=lambda x: self.start_background_removal())
        self.add_widget(self.start_button)

    def start_background_removal(self):
        input_dir = self.input_layout.text_input.text
        output_dir = self.output_layout.text_input.text
        self.start_button.text = "Processing files..."
        thread = threading.Thread(
            target=background_remover.batch_process_images, args=(input_dir, output_dir)
        )
        thread.start()
        thread.join()
        files_processed = background_remover.get_files_processed()
        if files_processed:
            self.start_button.text = f"Processed {files_processed} files."
        else:
            self.start_button.text = f"No files found. Processed 0 files."


class BackgroundRemovalApp(App):
    def build(self):
        self.title = "Batch Background Remover"
        return RootWidget()


if __name__ == "__main__":
    BackgroundRemovalApp().run()
