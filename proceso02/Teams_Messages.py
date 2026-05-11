# -*- coding: utf-8 -*-
"""
Created on Mon Jul 24 10:18:07 2023

@author: L03523797
"""

import requests
import json

class TeamsWebhook:
    def __init__(self, url):
        self.url = url

    def send_message(self, title, text):
        message = {
            "@context": "https://schema.org/extensions",
            "@type": "MessageCard",
            "themeColor": "0078D7",
            "title": title,
            "text": text
        }

        response = requests.post(self.url, json=message)

        if response.status_code == 200:
            print("Mensaje enviado exitosamente.")
        else:
            print(f"Hubo un problema al enviar el mensaje: {response.content}")
