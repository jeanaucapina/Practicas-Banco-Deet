"""Da de alta en un ChirpStack v4 (el de practicas/L10/pc) la pasarela del laboratorio,
un perfil US915 FSB 2 con el decodificador del Listado L10.4, una aplicacion y el nodo
del tablero. Es lo que el alumno hace a mano en la web en la Parte I (Paso 4); sirve
al docente para preparar una demostracion y a las pruebas del banco.

    python tablero/herramientas/l10_provisionar.py [--servidor 127.0.0.1:8089]
        [--deveui 0004A30B001F7A01] [--joineui ...] [--appkey ...]

Imprime el JoinEUI y la AppKey para copiarlos al programa del nodo.
Necesita: pip install chirpstack-api
"""

import argparse
import os
import secrets
import sys

import grpc
from chirpstack_api import api, common

AQUI = os.path.dirname(os.path.abspath(__file__))
DECODIFICADOR = os.path.join(AQUI, "..", "practicas", "L10", "pc", "decodificador.js")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--servidor", default="127.0.0.1:8089")
    ap.add_argument("--usuario", default="admin")
    ap.add_argument("--clave", default="admin")
    ap.add_argument("--pasarela", default="A84041FFFE1F7603")
    ap.add_argument("--deveui", default="0004A30B001F7A01")
    ap.add_argument("--nombre", default="banco-t1")
    ap.add_argument("--joineui", default="70B3D57ED0000010")
    ap.add_argument("--appkey", default="")
    a = ap.parse_args()
    appkey = a.appkey or secrets.token_hex(16).upper()

    canal = grpc.insecure_channel(a.servidor)
    tok = api.InternalServiceStub(canal).Login(api.LoginRequest(email=a.usuario, password=a.clave)).jwt
    md = [("authorization", "Bearer " + tok)]

    inquilinos = api.TenantServiceStub(canal).List(api.ListTenantsRequest(limit=10), metadata=md)
    tenant = inquilinos.result[0].id

    gws = api.GatewayServiceStub(canal)
    try:
        gws.Get(api.GetGatewayRequest(gateway_id=a.pasarela.lower()), metadata=md)
    except grpc.RpcError:
        gws.Create(api.CreateGatewayRequest(gateway=api.Gateway(
            gateway_id=a.pasarela.lower(), name="pasarela-laboratorio", tenant_id=tenant,
            stats_interval=30)), metadata=md)
        print("pasarela", a.pasarela, "registrada")

    dps = api.DeviceProfileServiceStub(canal)
    perfiles = dps.List(api.ListDeviceProfilesRequest(tenant_id=tenant, limit=50), metadata=md)
    dp = next((p.id for p in perfiles.result if p.name == "banco-us915-fsb2"), None)
    if dp is None:
        with open(DECODIFICADOR, encoding="utf-8") as f:
            codec = f.read()
        dp = dps.Create(api.CreateDeviceProfileRequest(device_profile=api.DeviceProfile(
            tenant_id=tenant, name="banco-us915-fsb2", region=common.Region.US915,
            region_config_id="us915_1", mac_version=common.MacVersion.LORAWAN_1_0_4,
            reg_params_revision=common.RegParamsRevision.RP002_1_0_3, supports_otaa=True,
            uplink_interval=600, adr_algorithm_id="default",
            payload_codec_runtime=api.CodecRuntime.JS, payload_codec_script=codec)), metadata=md).id
        print("perfil banco-us915-fsb2 creado")

    aps = api.ApplicationServiceStub(canal)
    apps = aps.List(api.ListApplicationsRequest(tenant_id=tenant, limit=50), metadata=md)
    app = next((x.id for x in apps.result if x.name == "informatica-industrial"), None)
    if app is None:
        app = aps.Create(api.CreateApplicationRequest(application=api.Application(
            tenant_id=tenant, name="informatica-industrial")), metadata=md).id
        print("aplicacion informatica-industrial creada")

    ds = api.DeviceServiceStub(canal)
    try:
        ds.Delete(api.DeleteDeviceRequest(dev_eui=a.deveui.lower()), metadata=md)
    except grpc.RpcError:
        pass
    ds.Create(api.CreateDeviceRequest(device=api.Device(
        dev_eui=a.deveui.lower(), name=a.nombre, application_id=app, device_profile_id=dp,
        join_eui=a.joineui.lower(), skip_fcnt_check=False)), metadata=md)
    ds.CreateKeys(api.CreateDeviceKeysRequest(device_keys=api.DeviceKeys(
        dev_eui=a.deveui.lower(), nwk_key=appkey.lower())), metadata=md)    # 1.0.x: nwk_key = AppKey
    print("nodo %s (%s) registrado en la aplicacion %s" % (a.nombre, a.deveui, app))
    print("JOIN_EUI =", a.joineui.upper())
    print("APP_KEY  =", appkey)
    print("APP_ID   =", app)


if __name__ == "__main__":
    sys.exit(main())
