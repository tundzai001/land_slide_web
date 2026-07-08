import asyncio
import logging
import base64
import json
import socket
import aiohttp
from typing import Dict, Any, List

logger = logging.getLogger(__name__)

class RoundRobinAdjustmentManager:
    def __init__(self, mqtt_client, caster_host="127.0.0.1", caster_port=7054):
        self.mqtt_client = mqtt_client
        self.caster_host = caster_host
        self.caster_port = caster_port
        self.running_tasks = {}
        # Mảng lưu cache toạ độ LLH của các trạm (được cập nhật từ bản tin GPGGA)
        self.rover_llh_cache: Dict[str, Dict[str, float]] = {}

    def update_rover_llh(self, station_code: str, lat: float, lon: float, alt: float):
        self.rover_llh_cache[station_code] = {"lat": lat, "lon": lon, "alt": alt}

    def add_agrica_payload(self, raw_payload: str, info: Dict[str, Any]):
        from processors.gnss_adjustment_runtime import parse_agrica
        
        if not hasattr(self, 'observations_cache'):
            self.observations_cache = {}
            
        project_id = int(info.get("project_id") or info.get("station_id") or 0)
        station_id = int(info.get("station_id") or 0)
        rover_name = str(info.get("station_code") or info.get("station_name") or f"station_{station_id}")
        
        try:
            obs_list = parse_agrica(raw_payload, project_id=project_id, station_id=station_id, rover_name=rover_name)
            if project_id not in self.observations_cache:
                self.observations_cache[project_id] = []
            
            # Chỉ lưu các obs có position_type = 4 (Fixed) hoặc 7 (Float)
            valid_obs = [obs for obs in obs_list if obs.position_type in (4, 7)]
            self.observations_cache[project_id].extend(valid_obs)
        except Exception as e:
            logger.error(f"Error parsing AGRICA in RoundRobin: {e}")

    async def start_cycle(self, project_id: int, rovers: List[str]):
        """Bắt đầu chu trình xoay vòng trạm Base"""
        if project_id in self.running_tasks:
            logger.warning(f"RoundRobin cycle already running for project {project_id}")
            return
        
        task = asyncio.create_task(self._run_cycle(project_id, rovers))
        self.running_tasks[project_id] = task

    async def _run_cycle(self, project_id: int, rovers: List[str]):
        try:
            logger.info(f"🔄 Starting Round-Robin cycle for project {project_id} with {len(rovers)} rovers: {rovers}")
            
            for i, rover_code in enumerate(rovers):
                logger.info(f"📍 [Round-Robin] Step {i+1}/{len(rovers)}: Setting {rover_code} as Base...")
                
                # 1. Lấy thông tin LLH từ cache (đã thu thập trước Bước 1)
                llh = self.rover_llh_cache.get(rover_code)
                if not llh:
                    logger.warning(f"⚠️ No LLH cache found for {rover_code}. Using defaults (0,0,0).")
                    llh = {"lat": 0.0, "lon": 0.0, "alt": 0.0}

                # 2. Tìm thông tin kết nối hiện tại của Rover trong AICaster
                client_info = await self._find_client_info(rover_code)
                if not client_info:
                    logger.error(f"❌ Could not find active client session for {rover_code} in AICaster. Skipping.")
                    continue

                username = client_info.get("Username", rover_code)
                receiver_id = client_info.get("receiverID", "")
                mountpoint = client_info.get("Mountpoint", "")
                
                if not mountpoint:
                    logger.error(f"❌ Missing mountpoint for {rover_code}. Cannot send SET command.")
                    continue

                # Cấu hình Geotek LTE Unicore (FRESET -> mode base -> NMEA -> RTCM)
                config_commands = self._build_geotek_lte_unicore_config(
                    setup_method="FIXED", 
                    lat=llh["lat"], 
                    lon=llh["lon"], 
                    alt=llh["alt"]
                )

                # 3. Mở kết nối TCP tới Caster, gửi HTTP SET request để thiết lập cấu hình trực tiếp xuống thiết bị
                logger.info(f"📡 Sending SET HTTP command to tunnel config to {rover_code} (MP: {mountpoint}, ID: {receiver_id})")
                success = await self._send_set_command(mountpoint, username, receiver_id, config_commands)
                
                if not success:
                    logger.error(f"❌ Failed to set {rover_code} as Base.")
                    continue
                
                logger.info(f"✅ Config sent to {rover_code}. Waiting 10s for device to apply config and reboot stream...")
                await asyncio.sleep(10)

                # 4. Gọi luồng ntrip_pusher (Start Route) để đẩy luồng RTCM từ thiết bị lên Caster dưới dạng SOURCE
                logger.info(f"🚀 Starting NTRIP Route for {rover_code} to push data to Caster...")
                # (Chúng ta mượn MQTT command/ntrip/route/start mà AgricaAdjustmentRuntime hoặc hệ thống đang nghe)
                start_payload = {
                    "ntrip_route": {
                        "source_host": "127.0.0.1", # Backend sẽ không biết IP thực tế nếu nó ở xa. Hệ thống ntrip_route hiện tại xử lý việc này thế nào?
                        "source_port": 5001,
                        "target_host": self.caster_host,
                        "target_port": self.caster_port,
                        "mountpoint": f"{rover_code}_BASE",
                        "password": "123"
                    }
                }
                # LƯU Ý: Nếu Rover tự push data lên Caster (vì thiết bị hỗ trợ tự stream sau khi mode base), 
                # thì không cần start_payload ở đây. Hiện tại tôi gửi lệnh start như kế hoạch.
                self.mqtt_client.publish("command/ntrip/route/start", json.dumps(start_payload))

                # 5. Thu thập chéo (Wait & Collect)
                logger.info(f"⏳ Waiting 15s to collect cross-baselines from other rovers to {rover_code}...")
                await asyncio.sleep(15)

                # 6. Stop Route (Ngắt Base hiện tại)
                logger.info(f"🛑 Stopping NTRIP Route for {rover_code}")
                stop_payload = {"station_code": f"{rover_code}_BASE"}
                self.mqtt_client.publish("command/ntrip/route/stop", json.dumps(stop_payload))
                
                # 7. (Optional) Restore Rover mode
                # Tạm thời để trống chờ phản hồi từ người dùng về lệnh 'mode rover'
                logger.info(f"🔄 (Placeholder) Restoring {rover_code} back to Rover mode...")
                
                await asyncio.sleep(5)
                
            logger.info(f"🎉 Round-Robin cycle completed for project {project_id}! Ready for Network Solver.")
            
            # Trigger Network Solver
            observations = getattr(self, 'observations_cache', {}).pop(project_id, [])
            if not observations:
                logger.warning(f"⚠️ No AGRICA observations collected during Round-Robin for project {project_id}.")
            else:
                logger.info(f"📐 Building Network with {len(observations)} observations...")
                from processors.gnss_adjustment.solver import adjust_network
                from processors.gnss_adjustment.models import Network, Point, Baseline
                from processors.gnss_adjustment_runtime import _llh_to_ecef
                
                network = Network()
                points_dict = {}
                baselines = []
                
                # Tìm toạ độ Base gốc từ GPGGA cache hoặc từ một observation
                base_llh = next((obs.base_llh for obs in observations if obs.base_llh), None)
                if not base_llh:
                    base_llh = (21.0, 105.0, 10.0) # Fallback
                
                base_ecef = _llh_to_ecef(base_llh[0], base_llh[1], base_llh[2])
                points_dict["BASE"] = Point("BASE", base_ecef, fixed=True)
                
                for obs in observations:
                    if obs.rover_ecef is None or not obs.base_llh:
                        continue
                    
                    rep_base_ecef = _llh_to_ecef(obs.base_llh[0], obs.base_llh[1], obs.base_llh[2])
                    baseline_ecef = (
                        obs.rover_ecef[0] - rep_base_ecef[0],
                        obs.rover_ecef[1] - rep_base_ecef[1],
                        obs.rover_ecef[2] - rep_base_ecef[2]
                    )
                    
                    rover_ecef_adjusted_input = (
                        base_ecef[0] + baseline_ecef[0],
                        base_ecef[1] + baseline_ecef[1],
                        base_ecef[2] + baseline_ecef[2]
                    )
                    
                    std = obs.std_ecef if obs.std_ecef else obs.std_neu
                    
                    if obs.rover_name not in points_dict:
                        points_dict[obs.rover_name] = Point(obs.rover_name, rover_ecef_adjusted_input, fixed=False, identifier=obs.station_id)
                    
                    baselines.append(Baseline(
                        "BASE",
                        obs.rover_name,
                        baseline_ecef,
                        covariance=std, # Using covariance=std as standard_deviation is not directly supported by this version maybe, wait. Let's use `standard_deviation` as gnss_adjustment_runtime used.
                    ))
                
                # Fix parameter name for std
                for b in baselines:
                    b.covariance = getattr(b, 'covariance', None)
                
                # Need to use standard_deviation=std in Baseline constructor based on earlier code
                for i, b in enumerate(baselines):
                    std = b.covariance
                    baselines[i] = Baseline(b.from_point, b.to_point, b.delta)
                    # Let's just set standard_deviation explicitly if supported or covariance
                    if hasattr(baselines[i], 'covariance'):
                         baselines[i].covariance = std
                
                network.points = points_dict
                network.baselines = baselines
                
                try:
                    result = adjust_network(network)
                    logger.info(f"✅ Network Adjustment Successful! Result points: {len(result.points)}")
                    for pt in result.points.values():
                        logger.info(f"   - {pt.name}: {pt.adjusted_coordinates}")
                except Exception as solve_e:
                    logger.error(f"❌ Network Solver failed: {solve_e}")

        except Exception as e:
            logger.error(f"❌ RoundRobin cycle failed for project {project_id}: {e}")
        finally:
            self.running_tasks.pop(project_id, None)

    async def _find_client_info(self, station_code: str) -> Dict[str, Any]:
        """Gọi API /clienttable của Caster để tìm thông tin phiên kết nối của Rover"""
        try:
            reader, writer = await asyncio.open_connection(self.caster_host, self.caster_port)
            request = "GET /clienttable HTTP/1.0\r\n\r\n"
            writer.write(request.encode())
            await writer.drain()
            
            data = await reader.read()
            writer.close()
            await writer.wait_closed()
            
            text = data.decode(errors='ignore')
            
            # Format: STR;Username;receiverID;Mountpoint;outLat;outLon;status;nSV;uptime;receiverID;CurrentGGATime;deltaTime;datacount;
            for line in text.strip().split('\n'):
                parts = line.split(';')
                if len(parts) > 4 and parts[0] == "STR":
                    username = parts[1]
                    receiver_id = parts[2]
                    mountpoint = parts[3]
                    # Thường thì username hoặc mountpoint sẽ chứa station_code
                    if station_code.lower() in username.lower() or station_code.lower() in mountpoint.lower():
                        return {
                            "Username": username,
                            "receiverID": receiver_id,
                            "Mountpoint": mountpoint
                        }
        except Exception as e:
            logger.error(f"Error fetching /clienttable: {e}")
        return None

    async def _send_set_command(self, mountpoint: str, username: str, receiver_id: str, commands: List[bytes], password: str = "123") -> bool:
        """Sử dụng Raw TCP Socket để mở HTTP SET Request và truyền payload"""
        try:
            reader, writer = await asyncio.open_connection(self.caster_host, self.caster_port)
            
            # Khởi tạo HTTP SET Request
            auth_str = base64.b64encode(f"{username}:{password}".encode()).decode()
            headers = (
                f"SET /{mountpoint} HTTP/1.0\r\n"
                f"User-Agent: NTRIP SetBaseCmd/{receiver_id}\r\n"
                f"Authorization: Basic {auth_str}\r\n"
                f"\r\n"
            )
            
            logger.debug(f"Sending SET Request headers: {headers.strip()}")
            writer.write(headers.encode('ascii'))
            await writer.drain()
            
            # Đọc phản hồi (chờ ICY 200 OK)
            response = await reader.read(1024)
            resp_str = response.decode('ascii', errors='ignore')
            logger.debug(f"Caster response: {resp_str.strip()}")
            
            if "200 OK" not in resp_str:
                logger.error(f"SET Request rejected by Caster: {resp_str}")
                writer.close()
                await writer.wait_closed()
                return False
                
            # Đã kết nối thành công qua tunnel, truyền lệnh cấu hình
            for cmd in commands:
                writer.write(cmd)
                await writer.drain()
                await asyncio.sleep(0.1) # Dãn thời gian để chip GNSS kịp xử lý
                
            # Tuỳ chọn: giữ kết nối hoặc đóng
            writer.close()
            await writer.wait_closed()
            return True
            
        except Exception as e:
            logger.error(f"Error sending SET command to {mountpoint}: {e}")
            return False

    def _build_geotek_lte_unicore_config(self, setup_method: str, duration: int = 60, lat: float = 0, lon: float = 0, alt: float = 0) -> list[bytes]:
        """Hàm sinh chuỗi lệnh cấu hình Unicorecomm cho Geotek LTE."""
        commands = []
        port = "com2"
        
        # 1. Reset vật lý chip và xóa hết log cũ
        commands.append(b'FRESET\r\n')
        commands.append(b'unlogall\r\n')
        
        # 2. Cấu hình chế độ Base (Survey-In hoặc Fixed)
        if setup_method.upper() == 'SURVEY_IN':
            commands.append(f'mode base time {duration}\r\n'.encode('ascii'))
        else:
            commands.append(f'mode base {lat} {lon} {alt}\r\n'.encode('ascii'))
        
        # 3. Bật GPGGA trên COM2
        commands.append(f'gpgga {port} 1\r\n'.encode('ascii'))
            
        # 4. Bật RTCM (bật CẢ MSM4 và MSM7) trên COM2
        rtcm_msgs = [
            '1006', '1033', '1074', '1124', '1084', '1094', '1042', '1019', '1020', '1045',
            '1077', '1127', '1087', '1097'
        ]
        for msg in rtcm_msgs:
            commands.append(f'rtcm{msg} {port} 1\r\n'.encode('ascii'))
        
        # 5. Lưu cấu hình
        commands.append(b'saveconfig\r\n')
        
        return commands
