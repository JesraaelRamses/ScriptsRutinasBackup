#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import yaml
import logging
import time
from datetime import datetime
from netmiko import ConnectHandler, NetmikoTimeoutException, NetmikoAuthenticationException

# Configuración de logging
base_dir = os.path.dirname(os.path.abspath(__file__))
log_dir = os.path.join(base_dir, 'logs')
os.makedirs(log_dir, exist_ok=True)

log_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s', datefmt='%d-%m-%Y %H:%M:%S')
console_handler = logging.StreamHandler()
console_handler.setFormatter(log_formatter)

fecha_log = datetime.now().strftime('%d%m%Y')
log_file = os.path.join(log_dir, f'respaldo_{fecha_log}.log')
file_handler = logging.FileHandler(log_file, mode='a')
file_handler.setFormatter(log_formatter)

root_logger = logging.getLogger()
if root_logger.hasHandlers():
    root_logger.handlers.clear()
root_logger.setLevel(logging.INFO)
root_logger.addHandler(console_handler)
root_logger.addHandler(file_handler)

fecha = datetime.now().strftime('%d%m%Y')
fecha_carpeta = datetime.now().strftime('%d%m%Y')

PLATFORM_HOSTS = {
    "PE_MEXICO_1", "PE_MEXICO_2", "PE_MEXICO_3", "PE_MEXICO_4", "PE_MEXICO_5", "PE_MEXICO_6",
    "PE_VERACRUZ_1", "PE_VERACRUZ_2", "PE_VERACRUZ_3", "PE_VERACRUZ_4", "PE_VERACRUZ_5", "PE_VERACRUZ_6"
}

def filtrar_platform(salida):
    lineas_filtradas = []
    for linea in salida.splitlines():
        partes = linea.split()
        if len(partes) > 1:
            lineas_filtradas.append(' '.join(partes[:-1]))
        else:
            lineas_filtradas.append(linea)
    return '\n'.join(lineas_filtradas)

def conectar_y_ejecutar(dispositivo):
    host = dispositivo['ip']
    nombre = dispositivo['nombre']
    zona = dispositivo['zona']
    usuario = dispositivo.get('usuario', 'usuario')

    tipo_raw = dispositivo.get('tipo', 'cisco')
    if tipo_raw is None:
        tipo_raw = 'cisco'
     tipo = str(tipo_raw).lower().strip()

    logging.info(f"Procesando: {nombre} - tipo: {tipo}")

    device_type_map = {'cisco': 'cisco_ios', 'huawei': 'huawei'}
    params = {
        'device_type': device_type_map.get(tipo, 'cisco_ios'),
        'host': host,
        'username': usuario,
        'ssh_strict': False,
        'timeout': 30,
        'session_timeout': 60,
        'global_delay_factor': 2,
        'read_timeout_override': 120,
    }
    if 'password' in dispositivo and dispositivo['password']:
        params['password'] = dispositivo['password']
    else:
        params['use_keys'] = True

    # Depuración: mostrar el valor del secret
    secret_val = dispositivo.get('secret')
    logging.info(f"  -> Secret leído para {nombre}: '{secret_val}'")

    if tipo == 'cisco' and secret_val:
        params['secret'] = secret_val
        logging.info(f"  -> Secret añadido a parámetros")
    else:
        logging.info(f"  -> No se añade secret (tipo {tipo} o secret vacío)")

    try:
        logging.info(f"Conectando a {nombre} ({host}) tipo {tipo}")
        conexion = ConnectHandler(**params)

        # Limpiar buffer
        conexion.write_channel("\n")
        time.sleep(1)
        conexion.read_channel()

        # Obtener prompt
        prompt = conexion.find_prompt()
        logging.info(f"  -> Prompt inicial: {prompt}")

        # Deshabilitar paginación
        if tipo == 'cisco':
            conexion.send_command_timing("terminal length 0")
            time.sleep(1)
            conexion.read_channel()
        else:
            conexion.send_command_timing("screen-length 0 temporary")
            time.sleep(1)
            conexion.send_command_timing("scroll")
            time.sleep(1)
            conexion.read_channel()

        # Enable solo si es necesario (Cisco y prompt no termina en '#')
        if tipo == 'cisco':
            if 'secret' in params and not prompt.endswith('#'):
                conexion.enable()
                logging.info(f"  -> Modo enable activado para {nombre}")
            else:
                logging.info(f"  -> Ya en modo privilegiado o sin secret, se omite enable")

        # 1. Configuración
        if tipo == 'cisco':
            comando_cfg = "show running-config"
        else:
            comando_cfg = "display current-configuration"
        salida_cfg = conexion.send_command(comando_cfg, read_timeout=180)
        archivo_cfg = os.path.join(zona, f"{nombre}.cfg.{fecha}")
        with open(archivo_cfg, 'w') as f:
            f.write(salida_cfg)
        logging.info(f"  -> Config guardada en {archivo_cfg}")

        # 2. Interfaces
        if tipo == 'cisco':
            comando_ship = "show ip interface brief"
        else:
            comando_ship = "display ip interface brief"
        salida_ship = conexion.send_command(comando_ship, read_timeout=90)
        archivo_ship = os.path.join(zona, f"{nombre}.ship.{fecha}")
        with open(archivo_ship, 'w') as f:
            f.write(salida_ship)
        logging.info(f"  -> Interfaces guardadas en {archivo_ship}")

        # 3. Módulos/Platform
        if tipo == 'cisco':
            if nombre in PLATFORM_HOSTS:
                comando_mod = "show platform"
                salida_mod = conexion.send_command(comando_mod, read_timeout=120)
                salida_mod = filtrar_platform(salida_mod)
                logging.info(f"  -> Comando {comando_mod} (filtrado) ejecutado")
            else:
                comando_mod = "show module"
                salida_mod = conexion.send_command(comando_mod, read_timeout=120)
                logging.info(f"  -> Comando {comando_mod} ejecutado")
            archivo_mod = os.path.join(zona, f"{nombre}.mod.{fecha}")
            with open(archivo_mod, 'w') as f:
                f.write(salida_mod)
            logging.info(f"  -> Módulos guardados en {archivo_mod}")
        else:  # Huawei
            comandos_hw = ["display device", "display elabel", "display power", "display fan"]
            salida_hw = ""
            for cmd in comandos_hw:
                logging.info(f"  -> Ejecutando {cmd}")
                try:
                    output = conexion.send_command(cmd, read_timeout=120)
                    salida_hw += f"\n\n{'='*60}\nComando: {cmd}\n{'='*60}\n{output}"
                except Exception as e:
                    logging.warning(f"  -> Error en {cmd}: {e}")
                    salida_hw += f"\n\nError en {cmd}: {e}\n"
            archivo_mod = os.path.join(zona, f"{nombre}.mod.{fecha}")
            with open(archivo_mod, 'w') as f:
                f.write(salida_hw)
            logging.info(f"  -> Hardware guardado en {archivo_mod}")

        conexion.disconnect()
        return True, None

    except NetmikoTimeoutException as e:
        motivo = f"Timeout: {e}"
        logging.error(f"Error con {nombre}: {motivo}")
        return False, motivo
    except NetmikoAuthenticationException as e:
        motivo = f"Autenticación fallida: {e}"
        logging.error(f"Error con {nombre}: {motivo}")
        return False, motivo
    except Exception as e:
        motivo = f"Error Inesperado: {e}"
        logging.error(f"Error con {nombre}: {motivo}")
        return False, motivo

def main():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    yaml_file = os.path.join(base_dir, 'PEs.yaml')
    zonas_dir = os.path.join(base_dir, 'Zonas')

    if not os.path.exists(yaml_file):
        logging.error(f"No se encuentra {yaml_file}")
        return

    with open(yaml_file, 'r') as f:
        datos = yaml.safe_load(f)

    if isinstance(datos, list):
        dispositivos = datos
    elif isinstance(datos, dict):
        dispositivos = datos.get('dispositivos', [])
    else:
        logging.error("Formato YAML no reconocido.")
        return

    if not dispositivos:
        logging.warning("No hay dispositivos en el YAML.")
        return

    logging.info("=== LISTA DE DISPOSITIVOS LEÍDOS ===")
    for d in dispositivos:
        logging.info(f"Nombre: {d.get('nombre')}, Zona: {d.get('zona')}, Tipo: {d.get('tipo', 'cisco')}")
    logging.info("====================================")

    # Crear carpetas
    zonas = set(d['zona'] for d in dispositivos)
    for zona in zonas:
        ruta_zona = os.path.join(zonas_dir, zona)
        os.makedirs(ruta_zona, exist_ok=True)
        os.makedirs(os.path.join(ruta_zona, fecha_carpeta), exist_ok=True)

    exitosos = 0
    fallidos = 0
    fallos_detalle = []

    for disp in dispositivos:
        zona_nombre = disp['zona']
        ruta_completa = os.path.join(zonas_dir, zona_nombre, fecha_carpeta)
        disp['zona'] = ruta_completa
        exito, motivo = conectar_y_ejecutar(disp)
        if exito:
            exitosos += 1
        else:
            fallidos += 1
            fallos_detalle.append((zona_nombre, ruta_completa, disp['nombre'], motivo))

    # Reporte global
    reportes_dir = os.path.join(base_dir, 'Reportes')
    os.makedirs(reportes_dir, exist_ok=True)
    archivo_reporte = os.path.join(reportes_dir, f"Reporte_Incidentes.{fecha}")
    with open(archivo_reporte, 'w') as f:
        f.write(f"Reporte de Incidentes - {datetime.now().strftime('%d/%m/%Y')}\n")
        f.write("="*50 + "\n")
        if fallos_detalle:
            for zona, ruta, nombre, motivo in fallos_detalle:
                f.write(f"Zona: {zona} - Dispositivo: {nombre} - Motivo: {motivo}\n")
        else:
            f.write("No se presentaron fallos en ningún dispositivo.\n")
    logging.info(f"Reporte global generado: {archivo_reporte}")

    # Resumen consola
    if fallos_detalle:
        logging.info("========== Detalle de Fallas ==========")
        for zona, ruta, nombre, motivo in fallos_detalle:
            logging.info(f"  {nombre} (Zona {zona}): {motivo}")
        logging.info("========================================")
    else:
        logging.info("  No se presentaron Fallas en ningún dispositivo  ")

    logging.info(f"Proceso completado. Exitosos: {exitosos}, Fallidos: {fallidos}")
    logging.info("====================================================")

if __name__ == '__main__':
    main()
