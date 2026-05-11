import requests
import json
from typing import Any, Dict, List, Optional
import math
import time

# --- Constantes ---
# URL para el flujo de Power Automate. Centralizada para evitar duplicación.
POWER_AUTOMATE_URL = "https://defaultc65a3ea60f7c400b89345a6dc17056.45.environment.api.powerplatform.com:443/powerautomate/automations/direct/workflows/6b3e0eeef567420b89db1118f585e9ea/triggers/manual/paths/invoke?api-version=1&sp=%2Ftriggers%2Fmanual%2Frun&sv=1.0&sig=VpIot04mL-B0n8sKdEW_y4wvFUrnfv7-6Su_If1NUX0"
BATCH_SIZE = 10  # Tamaño de lote para notificaciones consolidadas.


# --- Funciones Principales de Orquestación ---

def main(opp_id: str, company_name: str, opp_name: str, title: str,
         document_list: Optional[List[Dict[str, str]]] = None,
         cadena_emails: Optional[str] = None,
         asesor: Optional[str] = None,
         zona: Optional[str] = None) -> None:
    """Orquesta el envío de una notificación INDIVIDUAL."""
    print("--- Iniciando proceso de notificación individual ---")
    
    # Prepara los argumentos específicos para el constructor de la tarjeta individual.
    card_builder_args = {
        "opp_id": opp_id,
        "company_name": company_name,
        "opp_name": opp_name,
        "document_list": document_list,
        "asesor": asesor,
        "zona": zona
        }
    
    # Delega la lógica de envío (general o por email) a la función auxiliar.
    _orchestrate_sending(
        base_title=title,
        card_builder=build_card_body,
        card_builder_args=card_builder_args,
        cadena_emails=cadena_emails
        )
    
    print("\n--- Proceso de notificación individual finalizado. ---")


def enviar_notificacion_consolidada(title: str, oportunidades_procesadas: List[Dict[str, Any]],
                                    cadena_emails: Optional[str] = None) -> None:
    """
    Orquesta el envío de notificaciones consolidadas, dividiéndolas en lotes
    y pausando entre cada envío para evitar errores de throttling.
    """
    print("--- Iniciando proceso de notificación consolidada ---")
    total_oportunidades = len(oportunidades_procesadas)
    total_batches = math.ceil(total_oportunidades / BATCH_SIZE)
    
    for i in range(total_batches):
        start_index = i * BATCH_SIZE
        end_index = start_index + BATCH_SIZE
        batch_oportunidades = oportunidades_procesadas[start_index:end_index]
        
        batch_title = f"{title} (Parte {i + 1} de {total_batches})" if total_batches > 1 else title
        
        print(f"--- Procesando lote {i + 1}/{total_batches} con {len(batch_oportunidades)} oportunidades ---")
        
        card_builder_args = {"oportunidades": batch_oportunidades}
        
        _orchestrate_sending(
            base_title=batch_title,
            card_builder=build_consolidated_card_body,
            card_builder_args=card_builder_args,
            cadena_emails=cadena_emails
            )
        
        if i < total_batches - 1:
            print("... Pausando por 5 segundos antes del siguiente lote ...")
            time.sleep(5)
    
    print("\n--- Proceso de notificación consolidada finalizado. ---")


# --- Funciones de Construcción de Tarjetas Adaptables ---

def build_card_body(title: str, opp_id: str, company_name: str, opp_name: str,
                    document_list: Optional[List[Dict[str, str]]],
                    asesor: Optional[str] = None,
                    zona: Optional[str] = None) -> List[Dict[str, Any]]:
    """Construye el cuerpo de la Tarjeta Adaptable para una notificación INDIVIDUAL."""
    facts = [
        {"title": "Empresa:", "value": company_name},
        {"title": "Oportunidad:", "value": opp_name},
        {"title": "Id Proyecto:", "value": opp_id}
        ]
    if asesor:
        facts.append({"title": "Asesor:", "value": asesor})
    if zona:
        facts.append({"title": "Zona:", "value": zona})
    
    document_elements = _build_document_elements(document_list)
    
    return [
        {"type": "Container", "style": "emphasis", "items": [
            {"type": "TextBlock", "text": title, "weight": "Bolder", "size": "Medium"}
            ]},
        {"type": "Container", "items": [
            {"type": "FactSet", "facts": facts},
            {"type": "TextBlock", "text": "**Documentos Registrados:**", "wrap": True, "separator": True},
            *document_elements
            ]}
        ]


def build_consolidated_card_body(title: str, oportunidades: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Construye el cuerpo de una Tarjeta Adaptable consolidada para un lote de oportunidades."""
    main_body_elements = [
        {"type": "Container", "style": "emphasis", "items": [
            {"type": "TextBlock", "text": title, "weight": "Bolder", "size": "Large"}
            ]}
        ]
    
    for index, opp in enumerate(oportunidades):
        if index > 0:
            main_body_elements.append({
                "type": "Container", "spacing": "ExtraLarge", "minHeight": "2px", "bleed": True,
                "backgroundImage": {
                    "url": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60eADAAAAABJRU5ErkJggg==",
                    "fillMode": "Repeat"
                    }
                })
        
        opp_elements = _build_single_opportunity_section(opp)
        main_body_elements.extend(opp_elements)
    
    return main_body_elements


# --- Funciones Auxiliares ---

def _orchestrate_sending(base_title: str, card_builder: callable, card_builder_args: Dict,
                         cadena_emails: Optional[str]) -> None:
    """
    Centraliza la lógica de envío, ya sea a un canal general o a usuarios específicos.
    """
    if cadena_emails and cadena_emails.strip():
        emails = [email.strip() for email in cadena_emails.strip().strip(';').split(';') if email.strip()]
        print(f"--- Dirigiendo envío a {len(emails)} usuario(s) ---")
        for email in emails:
            personal_title = f"{base_title} para <at>{email}</at>"
            card_body = card_builder(title=personal_title, **card_builder_args)
            trigger_power_automate_flow(card_body, user_email=email)
    else:
        print("--- Realizando envío general ---")
        card_body = card_builder(title=base_title, **card_builder_args)
        trigger_power_automate_flow(card_body)


def _build_document_elements(document_list: Optional[List[Dict[str, str]]]) -> List[Dict[str, Any]]:
    """Función auxiliar para construir la sección de documentos de una tarjeta."""
    if not document_list:
        return [{"type": "TextBlock", "text": "No se encontraron documentos.", "wrap": True}]
    
    elements = []
    for doc in document_list:
        doc_name = doc.get('Nombre', '')
        doc_type = doc.get('Tipo', '')
        text_block = {"type": "TextBlock", "spacing": "Small", "wrap": True}
        if "¡¡RIESGO!!" in doc_name:
            text_block.update({"text": f"**{doc_name}**", "color": "Attention", "size": "Medium"})
        else:
            extension = f".{doc_type}" if doc_type else ""
            text_block["text"] = f"• {doc_name}{extension}"
        elements.append(text_block)
    return elements


def _build_single_opportunity_section(opp: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Construye los elementos de una única oportunidad para la tarjeta consolidada."""
    fact_data = [
        {"title": "Empresa:", "value": opp.get('company_name', 'N/A')},
        {"title": "Oportunidad:", "value": opp.get('opp_name', 'N/A')},
        {"title": "Id Proyecto:", "value": opp.get('opp_id', 'N/A')}
        ]
    if opp.get('asesor'):
        fact_data.append({"title": "Asesor:", "value": opp.get('asesor')})
    if opp.get('zona'):
        fact_data.append({"title": "Zona:", "value": opp.get('zona')})
    
    fact_elements = [
        {"type": "ColumnSet", "spacing": "Small", "columns": [
            {"type": "Column", "width": "auto",
             "items": [{"type": "TextBlock", "text": fact["title"], "wrap": True, "weight": "Bolder"}]},
            {"type": "Column", "width": "stretch",
             "items": [{"type": "TextBlock", "text": fact["value"], "wrap": True, "isSubtle": True}]}
            ]} for fact in fact_data
        ]
    
    document_elements = _build_document_elements(opp.get('document_list', []))
    
    return [
        {"type": "Container", "items": [
            *fact_elements,
            {"type": "TextBlock", "text": "**Documentos Registrados:**", "wrap": True, "separator": True,
             "spacing": "Medium"},
            *document_elements
            ]}
        ]


def trigger_power_automate_flow(card_body_elements: List[Dict[str, Any]],
                                user_email: Optional[str] = None) -> None:
    """Envía la carga útil final al flujo de Power Automate."""
    msteams_block = {"width": "Full"}
    if user_email:
        msteams_block["entities"] = [
            {"type": "mention", "text": f"<at>{user_email}</at>",
             "mentioned": {"id": user_email, "name": user_email.split('@')[0]}}
            ]
    
    payload = {
        "type": "message",
        "attachments": [
            {"contentType": "application/vnd.microsoft.card.adaptive",
             "content": {
                 "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
                 "type": "AdaptiveCard",
                 "version": "1.2",
                 "body": card_body_elements,
                 "msteams": msteams_block
                 }}
            ]
        }
    
    headers = {'Content-Type': 'application/json'}
    try:
        response = requests.post(POWER_AUTOMATE_URL, headers=headers, json=payload, timeout=15)
        user_info = f"a {user_email}" if user_email else "de forma general"
        if response.status_code in [200, 202]:
            print(f"-> Notificación enviada exitosamente {user_info}.")
        else:
            print(f"-> Problema al enviar notificación {user_info}: {response.status_code} - {response.text}")
    except requests.exceptions.RequestException as e:
        print(f"-> Error de conexión al notificar por Teams: {e}")
