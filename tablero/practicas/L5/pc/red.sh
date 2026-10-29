#!/bin/sh
# Practica L5, itinerario C: la red reducida de la Parte III dentro de UN contenedor,
# con espacios de red (ip netns) y pares veth: nada de puentes de Docker por medio.
#
#   controlador 192.168.10.10 ─┐                 ┌─ servidor_control 192.168.10.50
#   camara      192.168.20.10 ─┤ sw2 ══ eth5 ══ sw1 ├─ servidor_vision  192.168.20.50
#                              │     ── eth6 ──    └─ hmi              192.168.99.10
#
# sw1 y sw2 son puentes Linux con VLAN 802.1Q (10 control, 20 video, 99 supervision):
# accesos sin etiqueta, eth5/eth6 troncales etiquetados. sw2 hace de gestor del anillo
# (como un MRM de MRP): eth6 es el redundante y queda fuera del puente mientras eth5
# este arriba; si eth5 cae, lo mete al cabo de T_RECONF_MS (200 ms) y lo saca al volver.
#
# Uso (desde tu computador):   docker exec -it l5 nodo sw2            una shell en sw2
#                              docker exec -it l5 nodo controlador ping 192.168.10.50
#                              docker exec l5 cortar | reponer         el troncal eth5
set -e
T=${T_RECONF_MS:-200}

ns() { ip netns add "$1"; ip -n "$1" link set lo up; }
for n in sw1 sw2 controlador camara servidor_control servidor_vision hmi; do ns "$n"; done

cable() {   # $1 nodo:interfaz  $2 nodo:interfaz
    a=${1%%:*}; ai=${1#*:}; b=${2%%:*}; bi=${2#*:}
    ip link add "x$$" type veth peer name "y$$"
    ip link set "x$$" netns "$a"; ip -n "$a" link set "x$$" name "$ai"
    ip link set "y$$" netns "$b"; ip -n "$b" link set "y$$" name "$bi"
    ip -n "$a" link set "$ai" up; ip -n "$b" link set "$bi" up
}
cable sw2:eth1 controlador:eth0
cable sw2:eth3 camara:eth0
cable sw2:eth5 sw1:eth5
cable sw2:eth6 sw1:eth6
cable sw1:eth1 servidor_control:eth0
cable sw1:eth3 servidor_vision:eth0
cable sw1:eth4 hmi:eth0

ipaddr() { ip -n "$1" addr add "$2" dev eth0; }
ipaddr controlador 192.168.10.10/24
ipaddr camara 192.168.20.10/24
ipaddr servidor_control 192.168.10.50/24
ipaddr servidor_vision 192.168.20.50/24
ipaddr hmi 192.168.99.10/24

puente() { ip -n "$1" link add br0 type bridge vlan_filtering 1; ip -n "$1" link set br0 up; }
acceso() { ip -n "$1" link set "$2" master br0; bridge -n "$1" vlan del dev "$2" vid 1; bridge -n "$1" vlan add dev "$2" vid "$3" pvid untagged; }
troncal() { ip -n "$1" link set "$2" master br0; bridge -n "$1" vlan del dev "$2" vid 1; for v in 10 20 99; do bridge -n "$1" vlan add dev "$2" vid $v; done; }
puente sw1; puente sw2
acceso sw2 eth1 10; acceso sw2 eth3 20; troncal sw2 eth5
acceso sw1 eth1 10; acceso sw1 eth3 20; acceso sw1 eth4 99; troncal sw1 eth5; troncal sw1 eth6
ip -n sw2 link set eth6 down          # el redundante, bloqueado (fuera del puente)

# Atajos para el alumno
cat > /usr/local/bin/nodo <<'FIN'
#!/bin/sh
n="$1"; shift
[ $# -eq 0 ] && exec ip netns exec "$n" sh -c "PS1='$n# ' exec sh"
exec ip netns exec "$n" "$@"
FIN
cat > /usr/local/bin/cortar <<'FIN'
#!/bin/sh
ip -n sw2 link set eth5 down; echo "$(date +%T.%N | cut -c1-12) troncal eth5 cortado"
FIN
cat > /usr/local/bin/reponer <<'FIN'
#!/bin/sh
ip -n sw2 link set eth5 up; echo "$(date +%T.%N | cut -c1-12) troncal eth5 repuesto"
FIN
chmod +x /usr/local/bin/nodo /usr/local/bin/cortar /usr/local/bin/reponer

echo "L5 lista: sw1, sw2, controlador, camara, servidor_control, servidor_vision, hmi"
bridge -n sw2 vlan show
echo "gestor del anillo en sw2: eth6 bloqueado; reconfiguracion en $T ms"
abierto=0
while true; do
    if [ "$(ip -n sw2 -o link show eth5 | grep -c 'state UP')" = 1 ] || \
       [ "$(ip -n sw2 -o link show eth5 | grep -c ',UP,')" = 1 ]; then
        if [ $abierto = 1 ]; then
            ip -n sw2 link set eth6 nomaster; ip -n sw2 link set eth6 down; abierto=0
            echo "$(date +%T.%N | cut -c1-12) eth5 de vuelta: eth6 bloqueado"
        fi
    elif [ $abierto = 0 ]; then
        sleep "$(awk "BEGIN{print $T/1000}")"
        ip -n sw2 link set eth6 up; troncal sw2 eth6; abierto=1
        echo "$(date +%T.%N | cut -c1-12) eth5 caido: eth6 abierto (anillo reconfigurado)"
    fi
    sleep 0.02
done
