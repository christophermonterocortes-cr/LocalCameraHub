import sys
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
import urllib.request
import re

def make_soap_response(body_xml):
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<SOAP-ENV:Envelope xmlns:SOAP-ENV="http://www.w3.org/2003/05/soap-envelope"
                   xmlns:tt="http://www.onvif.org/ver10/schema"
                   xmlns:tds="http://www.onvif.org/ver10/device/wsdl"
                   xmlns:trt="http://www.onvif.org/ver10/media/wsdl"
                   xmlns:tptz="http://www.onvif.org/ver20/ptz/wsdl">
  <SOAP-ENV:Body>
    {body_xml}
  </SOAP-ENV:Body>
</SOAP-ENV:Envelope>""".strip().encode("utf-8")

class OnvifPtzBridgeHandler(BaseHTTPRequestHandler):
    cam_id = "cam3"
    port = 8898
    host = "192.168.0.245"

    def log_message(self, format, *args):
        pass

    def do_POST(self):
        content_len = int(self.headers.get("Content-Length", 0))
        post_data = self.rfile.read(content_len).decode("utf-8", errors="ignore")
        base_xaddr = f"http://{self.host}:{self.port}/onvif"

        if "GetCapabilities" in post_data:
            resp = make_soap_response(f"""
    <tds:GetCapabilitiesResponse>
      <tds:Capabilities>
        <tt:Device>
          <tt:XAddr>{base_xaddr}/device_service</tt:XAddr>
        </tt:Device>
        <tt:Media>
          <tt:XAddr>{base_xaddr}/Media</tt:XAddr>
        </tt:Media>
        <tt:PTZ>
          <tt:XAddr>{base_xaddr}/PTZ</tt:XAddr>
        </tt:PTZ>
      </tds:Capabilities>
    </tds:GetCapabilitiesResponse>""")
        elif "GetServices" in post_data:
            resp = make_soap_response(f"""
    <tds:GetServicesResponse>
      <tds:Service>
        <tds:Namespace>http://www.onvif.org/ver10/device/wsdl</tds:Namespace>
        <tds:XAddr>{base_xaddr}/device_service</tds:XAddr>
        <tds:Version><tt:Major>2</tt:Major><tt:Minor>0</tt:Minor></tds:Version>
      </tds:Service>
      <tds:Service>
        <tds:Namespace>http://www.onvif.org/ver10/media/wsdl</tds:Namespace>
        <tds:XAddr>{base_xaddr}/Media</tds:XAddr>
        <tds:Version><tt:Major>2</tt:Major><tt:Minor>0</tt:Minor></tds:Version>
      </tds:Service>
      <tds:Service>
        <tds:Namespace>http://www.onvif.org/ver20/ptz/wsdl</tds:Namespace>
        <tds:XAddr>{base_xaddr}/PTZ</tds:XAddr>
        <tds:Version><tt:Major>2</tt:Major><tt:Minor>0</tt:Minor></tds:Version>
      </tds:Service>
    </tds:GetServicesResponse>""")
        elif "GetProfiles" in post_data:
            resp = make_soap_response("""
    <trt:GetProfilesResponse>
      <trt:Profiles token="PROFILE_000" fixed="true">
        <tt:Name>MainProfile</tt:Name>
        <tt:VideoSourceConfiguration token="V_SRC_000">
          <tt:Name>V_SRC_000</tt:Name>
          <tt:UseCount>1</tt:UseCount>
          <tt:SourceToken>V_SRC_000</tt:SourceToken>
          <tt:Bounds x="0" y="0" width="1280" height="720"/>
        </tt:VideoSourceConfiguration>
        <tt:VideoEncoderConfiguration token="V_ENC_000">
          <tt:Name>V_ENC_000</tt:Name>
          <tt:UseCount>1</tt:UseCount>
          <tt:Encoding>H264</tt:Encoding>
          <tt:Resolution>
            <tt:Width>1280</tt:Width>
            <tt:Height>720</tt:Height>
          </tt:Resolution>
          <tt:Quality>5</tt:Quality>
        </tt:VideoEncoderConfiguration>
        <tt:PTZConfiguration token="PTZ_CFG_000">
          <tt:Name>PTZ_CFG_000</tt:Name>
          <tt:UseCount>1</tt:UseCount>
          <tt:NodeToken>PTZ_NODE_000</tt:NodeToken>
          <tt:DefaultContinuousPanTiltVelocitySpace>http://www.onvif.org/ver10/tptz/PanTiltSpaces/VelocityGenericSpace</tt:DefaultContinuousPanTiltVelocitySpace>
        </tt:PTZConfiguration>
      </trt:Profiles>
    </trt:GetProfilesResponse>""")
        elif "GetVideoSources" in post_data:
            resp = make_soap_response("""
    <trt:GetVideoSourcesResponse>
      <trt:VideoSources token="V_SRC_000">
        <tt:Framerate>20</tt:Framerate>
        <tt:Resolution>
          <tt:Width>1280</tt:Width>
          <tt:Height>720</tt:Height>
        </tt:Resolution>
      </trt:VideoSources>
    </trt:GetVideoSourcesResponse>""")
        elif "GetConfigurations" in post_data or "GetConfiguration" in post_data:
            resp = make_soap_response("""
    <tptz:GetConfigurationsResponse>
      <tptz:PTZConfiguration token="PTZ_CFG_000">
        <tt:Name>PTZ_CFG_000</tt:Name>
        <tt:UseCount>1</tt:UseCount>
        <tt:NodeToken>PTZ_NODE_000</tt:NodeToken>
        <tt:DefaultContinuousPanTiltVelocitySpace>http://www.onvif.org/ver10/tptz/PanTiltSpaces/VelocityGenericSpace</tt:DefaultContinuousPanTiltVelocitySpace>
      </tptz:PTZConfiguration>
    </tptz:GetConfigurationsResponse>""")
        elif "GetConfigurationOptions" in post_data:
            resp = make_soap_response("""
    <tptz:GetConfigurationOptionsResponse>
      <tptz:PTZConfigurationOptions>
        <tt:Spaces>
          <tt:ContinuousPanTiltVelocitySpace>
            <tt:URI>http://www.onvif.org/ver10/tptz/PanTiltSpaces/VelocityGenericSpace</tt:URI>
            <tt:XRange><tt:Min>-1.0</tt:Min><tt:Max>1.0</tt:Max></tt:XRange>
            <tt:YRange><tt:Min>-1.0</tt:Min><tt:Max>1.0</tt:Max></tt:YRange>
          </tt:ContinuousPanTiltVelocitySpace>
        </tt:Spaces>
      </tptz:PTZConfigurationOptions>
    </tptz:GetConfigurationOptionsResponse>""")
        elif "GetPresets" in post_data:
            resp = make_soap_response("<tptz:GetPresetsResponse/>")
        elif "GetNodes" in post_data or "GetNode" in post_data:
            resp = make_soap_response("""
    <tptz:GetNodesResponse>
      <tptz:PTZNode token="PTZ_NODE_000">
        <tt:Name>PTZ_NODE_000</tt:Name>
        <tt:SupportedPTZSpaces>
          <tt:ContinuousPanTiltVelocitySpace>
            <tt:URI>http://www.onvif.org/ver10/tptz/PanTiltSpaces/VelocityGenericSpace</tt:URI>
            <tt:XRange><tt:Min>-1.0</tt:Min><tt:Max>1.0</tt:Max></tt:XRange>
            <tt:YRange><tt:Min>-1.0</tt:Min><tt:Max>1.0</tt:Max></tt:YRange>
          </tt:ContinuousPanTiltVelocitySpace>
        </tt:SupportedPTZSpaces>
        <tt:MaximumNumberOfPresets>0</tt:MaximumNumberOfPresets>
        <tt:HomeSupported>false</tt:HomeSupported>
      </tptz:PTZNode>
    </tptz:GetNodesResponse>""")
        elif "ContinuousMove" in post_data:
            x_match = re.search(r'x=["\']?([-0-9.]+)["\']?', post_data)
            y_match = re.search(r'y=["\']?([-0-9.]+)["\']?', post_data)
            x = float(x_match.group(1)) if x_match else 0.0
            y = float(y_match.group(1)) if y_match else 0.0
            
            direction = None
            if abs(x) > abs(y):
                if x > 0.05: direction = "right"
                elif x < -0.05: direction = "left"
            else:
                if y > 0.05: direction = "up"
                elif y < -0.05: direction = "down"

            if direction:
                try:
                    urllib.request.urlopen(f"http://127.0.0.1:8084/{self.cam_id}/ptz?dir={direction}", timeout=1)
                except Exception as e:
                    pass

            resp = make_soap_response("<tptz:ContinuousMoveResponse/>")
        elif "Stop" in post_data:
            try:
                urllib.request.urlopen(f"http://127.0.0.1:8084/{self.cam_id}/ptz?dir=stop", timeout=1)
            except Exception as e:
                pass
            resp = make_soap_response("<tptz:StopResponse/>")
        else:
            resp = make_soap_response("<SOAP-ENV:Fault><SOAP-ENV:Code><SOAP-ENV:Value>SOAP-ENV:Receiver</SOAP-ENV:Value></SOAP-ENV:Code><SOAP-ENV:Reason><SOAP-ENV:Text xml:lang=\"en\">Action Not Implemented</SOAP-ENV:Text></SOAP-ENV:Reason></SOAP-ENV:Fault>")

        self.send_response(200)
        self.send_header("Content-Type", "application/soap+xml; charset=utf-8")
        self.send_header("Content-Length", str(len(resp)))
        self.end_headers()
        self.wfile.write(resp)

def start_onvif_bridge(cam_id, port, host="192.168.0.245"):
    handler = type(f"Handler_{cam_id}", (OnvifPtzBridgeHandler,), {"cam_id": cam_id, "port": port, "host": host})
    server = HTTPServer(("0.0.0.0", port), handler)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    print(f"[ONVIF Bridge] Running for {cam_id} on port {port} (host: {host})")
    return server

if __name__ == "__main__":
    s3 = start_onvif_bridge("cam3", 8898)
    s4 = start_onvif_bridge("cam4", 8897)
    print("ONVIF Bridges active on 8898 (cam3) and 8897 (cam4). Press Ctrl+C to stop.")
    import time
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
