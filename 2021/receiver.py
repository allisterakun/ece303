# Written by S. Mevawala, modified by D. Gitzel

import logging

import string
import struct
import zlib

import channelsimulator
import utils
import sys
import socket

class Receiver(object):

    def __init__(self, inbound_port=50005, outbound_port=50006, timeout=10, debug_level=logging.INFO):
        self.logger = utils.Logger(self.__class__.__name__, debug_level)

        self.inbound_port = inbound_port
        self.outbound_port = outbound_port
        self.simulator = channelsimulator.ChannelSimulator(inbound_port=inbound_port, outbound_port=outbound_port,
                                                           debug_level=debug_level)
        self.simulator.rcvr_setup(timeout)
        self.simulator.sndr_setup(timeout)

    def receive(self):
        raise NotImplementedError("The base API class has no implementation. Please override and add your own.")


class BogoReceiver(Receiver):
    ACK_DATA = bytes(123)

    def __init__(self):
        super(BogoReceiver, self).__init__()

    def receive(self):
        self.logger.info("Receiving on port: {} and replying with ACK on port: {}".format(self.inbound_port, self.outbound_port))
        while True:
            try:
                 data = self.simulator.u_receive()  # receive data
                 self.logger.info("Got data from socket: {}".format(
                     data.decode('ascii')))  # note that ASCII will only decode bytes in the range 0-127
	         sys.stdout.write(data)
                 self.simulator.u_send(BogoReceiver.ACK_DATA)  # send ACK
            except socket.timeout:
                sys.exit()

class myReceiver(BogoReceiver):

    def __init__(self):
        super(myReceiver,self).__init__()

    def receive(self):
        self.logger.info("Receiving on port: {} and replying with ACK on port: {}".format(self.inbound_port, self.outbound_port))

        lower=0
        termination=False

        received_packets={}

        while not termination:
            try:
                received_packet=self.simulator.u_receive()

                # first check if it is "1011111" -> termination message
                if received_packet[0] & (~received_packet[1] & 0xFF) & received_packet[2] & received_packet[3] & received_packet[4] & received_packet[5] & received_packet[6] == 255:
                    self.logger.info("TERMINATION")
                    # send back "1011111" termination message and terminate
                    self.simulator.u_send(bytearray([255, 0] + [255]*5))
                    termination = True
                    break
                else:
                    received_seq_num_bin=received_packet[0:4]
                    received_data_len_bin=received_packet[4:8]
                    received_checksum_bin=received_packet[8:12]
                    received_data=received_packet[12:]

                    received_seq_num_int=struct.unpack(">i",received_seq_num_bin)[0]

                    self.logger.info("RECEIVED: {}".format(received_seq_num_int))

                    received_seq_num_bin_str=bin(received_seq_num_int)[2:].zfill(32)

                    checksum_bin_str=format(self.checksum(received_seq_num_bin_str,received_data),'b').zfill(32)
                    checksum_bin=bytearray(int(checksum_bin_str[i:i+8],2) for i in range(0,32,8))

                    # compare received checksum vs. checksum calculated from received packet
                    if received_checksum_bin==checksum_bin:
                        self.logger.info("UNCORRUPTED")
                        received_packets[received_seq_num_int]=received_data[:struct.unpack(">i",received_data_len_bin)[0]]

                        ones = 1111
                        return_msg = received_seq_num_bin + struct.pack(">i",ones)
                        self.simulator.u_send(return_msg)
                        self.logger.info("Replying ACK {}".format(received_seq_num_int))

                    else:
                        self.logger.info("CORRUPTED")

                        zeros = 0000
                        return_msg = received_seq_num_bin + struct.pack(">i",zeros)
                        self.simulator.u_send(return_msg)
                        self.logger.info("Replying ACK {}".format(received_seq_num_int))
            except socket.timeout as timeoutException:
                self.logger.info(str(timeoutException))
                pass

        self.logger.info("Writing to file")
        for key,value in sorted(received_packets.items()):
            sys.stdout.write(value)

        sys.exit()




    def checksum(self,seq_num_bin_str,data_bin):
        filled_data = string.join([string.zfill(n, 8) for n in map(lambda s: s[2:], map(bin, data_bin))], '')
        checksum = zlib.adler32(seq_num_bin_str + filled_data) & 0xffffffff
        sys.stdout.write(checksum)
        return checksum

if __name__ == "__main__":
    # test out BogoReceiver
    rcvr = myReceiver()
    rcvr.receive()
