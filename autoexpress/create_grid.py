import matplotlib.pyplot as plt
import glob
import pathlib
import sys
import matplotlib.image as mpimg

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from autoexpress_core import expression_names

def plot_images(images, labels, rows, cols, output_file):
    fig, axes = plt.subplots(rows, cols, figsize=(12, 12))
    fig.patch.set_facecolor("#333333")  # Set background color to dark grey
    for ax in axes.flat:
        ax.axis("off")
    for i, ax in enumerate(axes.flat):
        ax.imshow(images[i])
        ax.set_title(labels[i], color="white")  # Set title color to white
    plt.tight_layout()
    plt.savefig(output_file, facecolor=fig.get_facecolor())  # Save figure
    plt.show()


def create_sprites(images, rows, cols, output_file):
    fig, axes = plt.subplots(rows, cols, figsize=(12, 12))
    fig.patch.set_facecolor("#333333")  # Set background color to dark grey
    
    for ax in axes.flat:
        ax.axis("off")
    
    for i, ax in enumerate(axes.flat):
        ax.imshow(images[i])

    plt.subplots_adjust(left=0, right=1, top=1, bottom=0, wspace=0, hspace=0)
    plt.savefig(output_file, facecolor=fig.get_facecolor())  # Save figure
    plt.show()


def load_images_from_directory(directory):
    image_list = []
    for filename in glob.glob(directory + "/*.png"):
        image = mpimg.imread(filename)
        image_list.append(image)
    return image_list


def main():
    character_name = "Hinata" 
    input_dir = r"Output\Hinata"
    output_file = f"Output\\{character_name}_sprite.png"
    rows,cols = 4, 7

    labels = expression_names("anime")
    images = load_images_from_directory(input_dir)

    # plot_images(images, labels, rows, cols, output_file)
    create_sprites(images, rows, cols, output_file)

if __name__ == "__main__":
    main()
