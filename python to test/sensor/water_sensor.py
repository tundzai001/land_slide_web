import paho.mqtt.client as mqtt
from pymodbus.client import ModbusSerialClient
import time
import json
import logging
import socket
import configparser
import threading
import os
import math
import tkinter as tk
from tkinter import simpledialog, messagebox


config = configparser.ConfigParser()
home_dir = os.path.expanduser(f"~{os.getenv('SUDO_USER') or os.getenv('USER')}")

LICENSE_SECTION = "License"
license_path = os.path.join(home_dir, "Desktop", "license.txt")

desktop_path = os.path.join(home_dir, "Desktop", "config.ini")
config.read(desktop_path)

def get_rpi_serial():
    try:
        with open('/proc/cpuinfo', 'r') as f:
            for line in f:
                if line.startswith('Serial'):
                    return line.split(':')[1].strip()
    except Exception:
        return None

def get_license_code1(string_number):
    length = len(string_number)
    arr = [0] * (length + 1)
    narr = [0.0] * (length + 1)

    number = float(string_number)
    r_string = ""
    n = length

    number *= n
    arr[0] = int(number * math.pow(10.0, -float(n)))

    for i in range(1, length):
        number = number - float(arr[i - 1]) / math.pow(10.0, -float(n))
        n -= 1
        arr[i] = int(number * math.pow(10, -float(n)))

    arr[length] = (arr[length - 2] + arr[length - 1]) / 2 + 1
    narr[0] = arr[0]

    for i in range(1, length + 1):
        narr[i] = (narr[i - 1] + float(arr[i])) / 2;

    for i in range(length):
        A = narr[i + 1] * math.exp(-0.2)
        B = (math.log(arr[length], 10)) * math.pow(arr[i + 1], 0.2)
        D = str(int(round(A + B)))
        r_string = r_string + D

    return r_string

def save_license_to_config(code):
    config = configparser.ConfigParser()
    config[LICENSE_SECTION] = {'code': code}
    with open(license_path, 'w') as f:
        config.write(f)

def read_license_from_config():
    if not os.path.exists(license_path):
        return None
    config = configparser.ConfigParser()
    config.read(license_path)
    return config.get(LICENSE_SECTION, 'code', fallback=None)

def license_is_valid():
    SerialNumber = get_rpi_serial()
    if not SerialNumber:
        messagebox.showerror("Error", "Could not read Raspberry Pi serial number.")
        return False
    digits_only = ''.join(filter(str.isdigit, SerialNumber))
    if not digits_only:
        messagebox.showerror("Error", "Serial number has no digits.")
        return False

    newoutcode = ""
    new_string = ""
    if len(SerialNumber) > 10:
        n = len(SerialNumber) - 10
        newSNumber = SerialNumber[-n:]

        for c in newSNumber:
            if 'a' <= c <= 'z':
                new_char = c.upper()
                new_string += new_char
            else:
                new_string += c

        for char in new_string:
            newvalue = ord(char);
            newoutcode += str(newvalue);

        if (len(newoutcode) > 12):
            n1 = len(newoutcode) - 12
            newoutcode = newoutcode[-n1:]

        NewAtivatedCode = newoutcode#"485748546966"
    license_code = get_license_code1(NewAtivatedCode) #"756885565577"
    saved_code = read_license_from_config()

    return saved_code == license_code

def validate_and_save(user_input, root, license_code):
    if user_input == license_code:
        save_license_to_config(user_input)
        messagebox.showinfo("Success", "License verified and saved.")
        root.destroy()
        main()
    else:
        messagebox.showerror("Invalid", "Invalid license. Try again.")

def show_license_gui():
    SerialNumber = get_rpi_serial()

    newoutcode = ""
    new_string = ""
    if len(SerialNumber) > 10:
        n = len(SerialNumber) - 10
        newSNumber = SerialNumber[-n:]

        for c in newSNumber:
            if 'a' <= c <= 'z':
                new_char = c.upper()
                new_string += new_char
            else:
                new_string += c

        for char in new_string:
            newvalue = ord(char);
            newoutcode += str(newvalue);

        if (len(newoutcode) > 12):
            n1 = len(newoutcode) - 12
            newoutcode = newoutcode[-n1:]

        NewAtivatedCode = newoutcode
        license_code = get_license_code1(NewAtivatedCode)

    root = tk.Tk()
    root.title(f"License Activation for device:{SerialNumber}")
    root.geometry("300x150")
    root.resizable(False, False)

    label = tk.Label(root, text="Enter License Code:")
    label.pack(pady=10)

    entry = tk.Entry(root, width=30)
    entry.pack()

    def on_submit():
        user_input = entry.get().strip()
        validate_and_save(user_input, root, license_code)

    button = tk.Button(root, text="Activate", command=on_submit)
    button.pack(pady=10)

    root.protocol("WM_DELETE_WINDOW", root.quit)
    root.mainloop()

def Initialization():
    config = configparser.ConfigParser()
    config['DEFAULT'] = {}
    print('NUMBER_OF_SENSORS ')
    config['DEFAULT']['NUMBER_OF_SENSOR'] = input()

    for x in range(int(config['DEFAULT']['NUMBER_OF_SENSOR'])):
        sensor_num = x + 1
        config['DEFAULT'][f"SENSOR_TYPE_{sensor_num}"] = input(f"SENSOR_TYPE_{sensor_num}: ")
        config['DEFAULT'][f"SENSOR_NAME_{sensor_num}"] = input(f"SENSOR_NAME_{sensor_num}: ")
        config['DEFAULT'][f"MODBUS_PORT_{sensor_num}"] = input(f"MODBUS_PORT_{sensor_num}: ")
        config['DEFAULT'][f"MODBUS_BAUDRATE_{sensor_num}"] = input(f"MODBUS_BAUDRATE_{sensor_num}: ")
        config['DEFAULT'][f"MODBUS_UNIT_ID_{sensor_num}"] = input(f"MODBUS_UNIT_ID_{sensor_num}: ")
        config['DEFAULT'][f"HOLDING_REGISTER_ADDRESS_{sensor_num}"] = input(f"HOLDING_REGISTER_ADDRESS_{sensor_num}: ")
        config['DEFAULT'][f"HOLDING_REGISTER_COUNT_{sensor_num}"] = input(f"HOLDING_REGISTER_COUNT_{sensor_num}: ")
        return_data = input(f"RETURN_DATA_FORMAT_{sensor_num} (comma-separated integers): ")
        config['DEFAULT'][f"RETURN_DATA_FORMAT_{sensor_num}"] = return_data
        config['DEFAULT'][f"MQTT_TOPIC_{sensor_num}"] = input(f"MQTT_TOPIC_{sensor_num}: ")
        config['DEFAULT'][f"DATA_SCALE_{sensor_num}"] = input(f"DATA_SCALE_{sensor_num}: ")
        config['DEFAULT'][f"OFFSET_{sensor_num}"] = input(f"OFFSET_{sensor_num}: ")


    print('READ_DATA_INTERVAL: ')
    config['DEFAULT']['READ_DATA_INTERVAL'] = input()
    print('MQTT_BROKER: ')
    config['DEFAULT']['MQTT_BROKER'] = input()
    print('MQTT_PORT: ')
    config['DEFAULT']['MQTT_PORT'] = input()
    print('MQTT_TOPIC: ')
    config['DEFAULT']['MQTT_TOPIC'] = input()
    print('MQTT_CLIENT_ID: ')
    config['DEFAULT']['MQTT_CLIENT_ID'] = input()
    print('MQTT_USERNAME: ')
    config['DEFAULT']['MQTT_USERNAME'] = input()
    print('MQTT_PASSWORD: ')
    config['DEFAULT']['MQTT_PASSWORD'] = input()
    with open('config.ini', 'w') as configfile:
        config.write(configfile)

mqtt_client = mqtt.Client()

log_thread = None
reconnect_thread = None
reconnect_device_thread = {}

modbus_client_ = {}

for x in range(int(config['DEFAULT']['NUMBER_OF_SENSOR'])):
    sensor_num = x + 1
    modbus_client_[f"modbus_client_{sensor_num}"] = ModbusSerialClient(
        port=config['DEFAULT'].get(f"MODBUS_PORT_{sensor_num}"),
        baudrate=int(config['DEFAULT'].get(f"MODBUS_BAUDRATE_{sensor_num}"))
    )


def initialize_logger(log_to_file=False):
    formatter = logging.Formatter('%(message)s')
    log = logging.getLogger()
    log.setLevel(logging.INFO)

    for handler in log.handlers[:]:
        log.removeHandler(handler)

    if log_to_file:
        log_file = os.path.join(home_dir,"Desktop", "backup_data.log")
        file_handler = logging.FileHandler(log_file, mode="a")
        file_handler.setLevel(logging.INFO)
        file_handler.setFormatter(formatter)
        log.addHandler(file_handler)
    else:
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        log.addHandler(console_handler)


def connect_mqtt():
    mqtt_password = config.get('DEFAULT', 'MQTT_PASSWORD', raw=True)
    password_bytes = bytes(mqtt_password, "utf-8")
    MQTT_PORT = int(config['DEFAULT']['MQTT_PORT'])
    try:
        mqtt_client.username_pw_set(config['DEFAULT']['MQTT_USERNAME'], password_bytes)
        mqtt_client.connect(config['DEFAULT']['MQTT_BROKER'], MQTT_PORT, 60)
        logging.info(f"Connected to MQTT Broker: {config['DEFAULT']['MQTT_BROKER']}")
    except Exception:
        return False
    return True

def read_modbus_data(address1, count1, ID):
    try:
        client_key = f"modbus_client_{ID}"
        modbus_client = modbus_client_[client_key]

        if not modbus_connection(ID): 
            modbus_client.close()
            return None

        result = modbus_client.read_holding_registers(address=address1, count=count1, slave=1)
        if result.isError():
            print(f"Modbus Error: {result}")
            return None
        if not result.registers:
            return None
        else:
            data = str(result.registers)
            start_index, end_index = map(int, config['DEFAULT'][f'RETURN_DATA_FORMAT_{ID}'].split(','))
            try:
                send_data = float(data[start_index:end_index] if end_index != 0 else data[start_index:]) * float(config['DEFAULT'][f"DATA_SCALE_{ID}"]) + float(config['DEFAULT'][f"OFFSET_{ID}"])
                return send_data
            except Exception:
                return data
    except Exception as e:
        print(f"Error: {e}")
        return None

def modbus_connection(ID):
    port_key = f"MODBUS_PORT_{ID}"
    modbus_directory = str(config['DEFAULT'].get(port_key))
    return os.path.exists(modbus_directory)
        

def internet(host="8.8.8.8", port=53, timeout=3):
    try:
        socket.setdefaulttimeout(timeout)
        socket.socket(socket.AF_INET, socket.SOCK_STREAM).connect((host, port))
        return True
    except socket.error:
        return False

def reconnect_device(address, count, ID): 
    global reconnect_thread
    connected_device = False
    while not connected_device:
        message = {
            "sensortype": config['DEFAULT'][f"SENSOR_TYPE_{ID}"],
            "sensorname":  config['DEFAULT'][f"SENSOR_NAME_{ID}"],
            "modbus_id" : config['DEFAULT'][f"MODBUS_UNIT_ID_{ID}"],
            "timestamp": time.time(),
            "status": "Lost connection to Modbus Sensor. Trying to reconnect after 1 minute..."
            }
        message_json1 = json.dumps(message)
        if internet():
            logging.info(f"Lost connection to Modbus Sensor_{ID}. Trying to reconnect after 1 minute...")
            publish_mqtt(message_json1, ID)
        else:
            logging.info(f"Lost connection to Modbus Sensor_{ID}. Trying to reconnect after 1 minute...")
            if reconnect_thread is None or not reconnect_thread.is_alive():
                reconnect_thread = threading.Thread(target=reconnect, daemon=True)
                reconnect_thread.start()
        if read_modbus_data(address, count, ID) is not None:
            publish_mqtt("Reconnected to Modbus device successfully", ID)
            connected_device = True
        else:
            time.sleep(60)

def reconnect():
    connected = False
    log_file = os.path.join(home_dir,"Desktop", "backup_data.log")
    while not connected:
        print("Disconnected. Trying to reconnect after 1 minute")
        if connect_mqtt():
            connected = True
            logging.info("Reconnected Successfully")
            if os.path.exists(log_file):
                send_log_file_to_mqtt(log_file)
                os.remove(log_file)
        else:
            time.sleep(60)


def publish_mqtt(message, ID):
    try:
        topic = config['DEFAULT'][f"MQTT_TOPIC_{ID}"]
        mqtt_client.publish(topic, message)
        logging.info(f"Published message to MQTT: {message}")
    except Exception as e:
        logging.error(f"Failed to publish message: {e}")

def write_data_to_log():
    global reconnect_device_thread
    latency = int(config['DEFAULT']['READ_DATA_INTERVAL'])
    while not internet():
        for x in range (int(config['DEFAULT']['NUMBER_OF_SENSOR'])):
            initialize_logger(log_to_file=True) 
            modbus_data = read_modbus_data(int(config['DEFAULT'].get(f"HOLDING_REGISTER_ADDRESS_{x+1}")), int(config['DEFAULT'].get(f"HOLDING_REGISTER_COUNT_{x+1}")), int(config['DEFAULT'].get(f"MODBUS_UNIT_ID_{x+1}")))
            message = {
            "sensortype": config['DEFAULT'][f"SENSOR_TYPE_{x+1}"],
            "sensorname":  config['DEFAULT'][f"SENSOR_NAME_{x+1}"],
            "modbus_id" : config['DEFAULT'][f"MODBUS_UNIT_ID_{x + 1}"],
            "timestamp": time.time(),
            "value": modbus_data,
            "status": "Normal"
            }
            if modbus_data is None:
                initialize_logger(log_to_file=False)
                if x not in reconnect_device_thread or not reconnect_device_thread[x].is_alive():
                        reconnect_device_thread[x] = threading.Thread(
        target=reconnect_device,
        name=f"ReconnectDeviceThread_{x+1}",
        args=(
            int(config['DEFAULT'].get(f"HOLDING_REGISTER_ADDRESS_{x+1}")),
            int(config['DEFAULT'].get(f"HOLDING_REGISTER_COUNT_{x+1}")),
            int(config['DEFAULT'].get(f"MODBUS_UNIT_ID_{x+1}"))
        ),
        daemon=True
    )
                        reconnect_device_thread[x].start()

            else:
                message_json = json.dumps(message)
                logging.info(str(message_json))
                time.sleep(latency)

def send_log_file_to_mqtt(log_file_path):
    try:
        with open(log_file_path, "r") as log_file:
            for line in log_file:
                if not internet():
                    reconnect()
                try:
                    data = json.loads(line)
                    sensor_id = data.get("modbus_id")
                    topic = config['DEFAULT'].get(f"MQTT_TOPIC_{sensor_id}")
                    sensor_id = data.get("modbus_id")
                    if not sensor_id:
                        for x in range (int(config['DEFAULT']['NUMBER_OF_SENSOR'])):
                            if data == f"Lost connection to Modbus Sensor_{x+1}. Trying to reconnect after 1 minute..." :
                                topic = config['DEFAULT'].get(f"MQTT_TOPIC_{x+1}")
                                break
                        continue
                except Exception as e:
                    topic = 'modbus_error'
                    print(e)
                message = line.strip()
                logging.info(f"Sending log to MQTT: {message}")
                mqtt_client.publish(topic, message)
                time.sleep(0.5)
    except FileNotFoundError:
        print(f"Error: The log file {log_file_path} does not exist.")
    except Exception as e:
        print(f"Error while sending log data: {e}")


def main():
    global log_thread, reconnect_thread, reconnect_device_thread
    root = tk.Tk()
    root.withdraw()
    latency = int(config['DEFAULT']['READ_DATA_INTERVAL'])
    connect_mqtt()
    while True:
        for x in range (int(config['DEFAULT']['NUMBER_OF_SENSOR'])):
            modbus_data = read_modbus_data(int(config['DEFAULT'].get(f"HOLDING_REGISTER_ADDRESS_{x+1}")), int(config['DEFAULT'].get(f"HOLDING_REGISTER_COUNT_{x+1}")), int(config['DEFAULT'].get(f"MODBUS_UNIT_ID_{x+1}")))
            message = {
            "sensortype": config['DEFAULT'][f"SENSOR_TYPE_{x+1}"],
            "sensorname":  config['DEFAULT'][f"SENSOR_NAME_{x+1}"],
            "modbus_id" : config['DEFAULT'][f"MODBUS_UNIT_ID_{x + 1}"],
            "timestamp": time.time(),
            "value": modbus_data,
            "status": "Normal"
            }
            message_json1 = json.dumps(message)
            if internet():
                if modbus_data is not None:
                    initialize_logger(log_to_file=False)
                    publish_mqtt(str(message_json1), int(x+1))
                    time.sleep(latency)
                else:
                    initialize_logger(log_to_file=False)
                    if x not in reconnect_device_thread or not reconnect_device_thread[x].is_alive():
                        reconnect_device_thread[x] = threading.Thread(
        target=reconnect_device,
        name=f"ReconnectDeviceThread_{x+1}",
        args=(
            int(config['DEFAULT'].get(f"HOLDING_REGISTER_ADDRESS_{x+1}")),
            int(config['DEFAULT'].get(f"HOLDING_REGISTER_COUNT_{x+1}")),
            int(config['DEFAULT'].get(f"MODBUS_UNIT_ID_{x+1}"))
        ),
        daemon=True
    )
                        reconnect_device_thread[x].start()
            else:
                if log_thread is None or not log_thread.is_alive():
                    log_thread = threading.Thread(target=write_data_to_log, daemon=True)
                    log_thread.start()

                if reconnect_thread is None or not reconnect_thread.is_alive():
                    reconnect_thread = threading.Thread(target=reconnect, daemon=True)
                    reconnect_thread.start()

if __name__ == "__main__":
    if license_is_valid():
        main()
    else:
        show_license_gui()
