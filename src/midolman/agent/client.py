import socket
import sys

data = " ".join(sys.argv[1:])

sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

sock.connect(('localhost', 8999))
#sock.send(data + "\n")
sock.send(data)
print "Sent %s" % data
result = sock.recv(1024)
print "Got %s" % result
sock.close()
