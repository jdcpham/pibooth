# -*- coding: utf-8 -*-

import time
import pygame
try:
    import cv2
    import numpy as np
except ImportError:
    cv2 = None  # OpenCV is optional
from PIL import Image
from pibooth.pictures import sizing
from pibooth.config.parser import PiConfigParser
from pibooth.utils import PoolingTimer
from pibooth.controls.camera.base import BaseCamera, LANGUAGES


def cv_camera_connected():
    """Return True if a camera compatible with OpenCV is found.
    """
    if not cv2:
        return False  # OpenCV is not installed

    camera = cv2.VideoCapture(0)
    if camera.isOpened():
        camera.release()
        return True

    return False


class CvCamera(BaseCamera):

    """OpenCV camera management.
    """

    IMAGE_EFFECTS = [u'none',
                     u'blur',
                     u'contour',
                     u'detail',
                     u'edge_enhance',
                     u'edge_enhance_more',
                     u'emboss',
                     u'find_edges',
                     u'smooth',
                     u'smooth_more',
                     u'sharpen']

    def __init__(self, iso=200, resolution=(1920, 1080), rotation=0, flip=False):
        BaseCamera.__init__(self, resolution)
        self._preview_hflip = False
        self._capture_hflip = flip
        self._rotation = rotation
        self._iso = iso
        self._overlay_mask = None

        self._cam = cv2.VideoCapture(0)
        self._cam.set(cv2.CAP_PROP_FRAME_WIDTH, self.resolution[0])
        self._cam.set(cv2.CAP_PROP_FRAME_HEIGHT, self.resolution[1])
        self._cam.set(cv2.CAP_PROP_ISO_SPEED, self._iso)

    def _show_overlay(self, text, alpha):
        """Add an image as an overlay.
        """
        if self._window:  # No window means no preview displayed
            rect = self.get_rect()
            pil_image = self.build_overlay((rect.width, rect.height), str(text), alpha)
            overlay = np.array(pil_image)

            # Detect which pixels in the overlay have something in them
            # and make a binary mask out of it
            overlay_mask = cv2.cvtColor(overlay, cv2.COLOR_RGBA2GRAY)
            res, overlay_mask = cv2.threshold(overlay_mask, 10, 1, cv2.THRESH_BINARY_INV)

            # Expand the mask from 1-channel to 3-channel
            height, width = overlay_mask.shape
            self._overlay_mask = np.repeat(overlay_mask, 3).reshape((height, width, 3))

            # Remove alpha from overlay
            self._overlay = cv2.cvtColor(overlay, cv2.COLOR_RGBA2RGB)

    def _fit_to_resolution(self, image):
        """Resize and crop to fit the desired resolution.
        """
        # Same process as RPI camera (almost), this is for keeping
        # final rendering sizing (see pibooth.picutres.maker)
        height, width = image.shape[:2]
        size = sizing.new_size_keep_aspect_ratio((width, height), self.resolution, 'outer')
        image = cv2.resize(image, size, interpolation=cv2.INTER_AREA)
        height, width = image.shape[:2]
        cropped = sizing.new_size_by_croping((width, height), self.resolution)
        return image[cropped[1]:cropped[3], cropped[0]:cropped[2]]

    def _get_preview_image(self):
        """Capture a new preview image.
        """
        rect = self.get_rect()

        ret, image = self._cam.read()
        if not ret:
            return

        image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        image = self._fit_to_resolution(image)

        if self._preview_hflip:
            image = cv2.flip(image, 1)

        # Resize to fit the available space in the window
        height, width = image.shape[:2]
        size = sizing.new_size_keep_aspect_ratio((width, height),  (rect.width, rect.height), 'outer')
        image = cv2.resize(image, size, interpolation=cv2.INTER_AREA)

        if self._overlay is not None:
            # Mask out the pixels that you want to overlay
            image *= self._overlay_mask
            # Put the overlay on
            image += self._overlay
        return Image.fromarray(image)

    def _post_process_capture(self, capture_path):
        """Rework and return a Image object from file.
        """
        image, effect = self._captures[capture_path]

        image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        image = self._fit_to_resolution(image)

        if self._capture_hflip:
            image = cv2.flip(image, 0)

        if effect != 'none':
            pass  # To be implemented

        cv2.imwrite(capture_path, image)
        return Image.fromarray(image)

    def preview(self, window, flip=True):
        """Setup the preview.
        """
        self._window = window
        self._preview_hflip = flip
        self._window.show_image(self._get_preview_image())

    def preview_countdown(self, timeout, alpha=80):
        """Show a countdown of `timeout` seconds on the preview.
        Returns when the countdown is finished.
        """
        timeout = int(timeout)
        if timeout < 1:
            raise ValueError("Start time shall be greater than 0")

        timer = PoolingTimer(timeout)
        while not timer.is_timeout():
            remaining = int(timer.remaining() + 1)
            if self._overlay is None or remaining != timeout:
                # Rebluid overlay only if remaining number has changed
                self._show_overlay(str(remaining), alpha)
                timeout = remaining

            updated_rect = self._window.show_image(self._get_preview_image())
            pygame.event.pump()
            if updated_rect:
                pygame.display.update(updated_rect)

        self._show_overlay(LANGUAGES.get(PiConfigParser.language, LANGUAGES['en']).get('smile_message'), alpha)
        self._window.show_image(self._get_preview_image())

    def preview_wait(self, timeout, alpha=80):
        """Wait the given time.
        """
        timeout = int(timeout)
        if timeout < 1:
            raise ValueError("Start time shall be greater than 0")

        timer = PoolingTimer(timeout)
        while not timer.is_timeout():
            updated_rect = self._window.show_image(self._get_preview_image())
            pygame.event.pump()
            if updated_rect:
                pygame.display.update(updated_rect)

        self._show_overlay(LANGUAGES.get(PiConfigParser.language, LANGUAGES['en']).get('smile_message'), alpha)
        self._window.show_image(self._get_preview_image())

    def stop_preview(self):
        """Stop the preview.
        """
        self._hide_overlay()
        self._window = None

    def capture(self, filename, effect=None):
        """Capture a new picture.
        """
        effect = str(effect).lower()
        if effect not in self.IMAGE_EFFECTS:
            raise ValueError("Invalid capture effect '{}' (choose among {})".format(effect, self.IMAGE_EFFECTS))

        ret, image = self._cam.read()
        if not ret:
            raise IOError("Can not capture frame")

        self._captures[filename] = (image, effect)
        time.sleep(0.5)  # To let time to see "Smile"

        self._hide_overlay()  # If stop_preview() has not been called

    def quit(self):
        """Close the camera driver, it's definitive.
        """
        if self._cam:
            self._cam.release()
