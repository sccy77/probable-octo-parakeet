# main yjh.py
"""
@brief 主调度入口



"""
import ujson
from machine import UART
import time
from configy import*
from sensor_manager import get_data
from hardware import hardware_init,oled_init,set_fan,oled_update

# 串口初始化，和EC200U通信
uart = UART(2, baudrate=9600, bits=8, parity=None, stop=1)

def send_uart_json(temperature, humidity, dew_margin, fan_state, risk):
    pkg = {
        "temperature": temperature,
        "humidity": humidity,
        "dew": dew_margin,
        "fan_state": fan_state,
        "risk": risk
    }
    buf = ujson.dumps(pkg) + "\r\n"
    uart.write(buf)
    print("uart send:", buf)



def main():
    hardware_init()
    oled_init()

    while True:
        data = get_data()
        p1 = data["point1"]

        if not p1["valid"]:
            set_fan(False)
            oled_update(-99, -99, False)
        else:
            t = p1["temperature"]
            h = p1["humidity"]
            dew_margin = p1["dew_margin"]
            fan_need_on = dew_margin < configy.DEW_MARGIN_DANGER_C
            set_fan(fan_need_on)
            oled_update(t, h, fan_need_on)

    
    # 新增：计算风险等级 + 串口上报JSON给EC200U
    if dew_margin < configy.DEW_MARGIN_DANGER_C:
        risk = 2
    elif dew_margin < configy.DEW_MARGIN_WARN_C:
        risk = 1
    else:
        risk = 0
    send_uart_json(t, h, dew_margin, fan_need_on, risk)




        time.sleep(configy.SAMPLE_PERIOD_S)


if __name__ == "__main__":
    main()

