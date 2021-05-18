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

        expected=0
        termination=False

        received_packets={}

        buffed = False
        ack_seq_num_bin_str="{0:b}".format(0).zfill(32)
        ack_seq_num_bin=bytearray(int(ack_seq_num_bin_str[i:i+8],2) for i in range(0,32,8))
        ones = 1111
        gapDetected = False
        lostPacket = []
        subtracker = 0

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

                        return_msg = self.createReturn(received_seq_num_int+1)

                        if gapDetected:
                            if received_seq_num_int in lostPacket:
                                lostPacket.remove(received_seq_num_int)
                            elif received_seq_num_int == subtracker:
                                # update subtracker for next consecutive sequence
                                subtracker = received_seq_num_int + 1
                            elif received_seq_num_int > subtracker:
                                # new gap detected
                                for j in range(subtracker,received_seq_num_int):
                                    lostPacket.append(j)
                                lostPacket = self.removeDup(lostPacket)
                                self.logger.info("New Gap Detected " + str(lostPacket))
                                subtracker = received_seq_num_int+1
                                
                            if len(lostPacket) == 0:
                                # all gap filled
                                expected = subtracker
                                gapDetected = False
                            else:
                                # next lost packet
                                lostPacket = self.removeDup(lostPacket)
                                expected = lostPacket[0]
                            
                            return_msg = self.createReturn(expected)
                            self.simulator.u_send(return_msg)
                            self.logger.info("Reply ACK " + str(expected))
                            self.logger.info("subtracker " + str(subtracker) )

                        elif received_seq_num_int == expected and (not buffed):
                            buffed = True
                            expected = expected +1
                        elif received_seq_num_int == expected:
                            self.simulator.u_send(return_msg)
                            
                            buffed = False
                            expected = expected + 1
                            
                            self.logger.info("Received and buffed Replying ACK {}".format(received_seq_num_int+1))

                        elif received_seq_num_int < expected:
                            # duplicate packet received
                            return_msg = self.createReturn(expected)
                            self.simulator.u_send(return_msg)
                            self.logger.info("Reply ack for dup "+ str(expected))
                        elif received_seq_num_int > expected:
                            # There is out of order detected
                            # Imediately send two last 
                            return_msg = self.createReturn(expected)
                            self.simulator.u_send(return_msg)
                            self.simulator.u_send(return_msg)

                            self.logger.info("Gap detected Replying ACK expeted" + str(expected))
                            self.logger.info("Lost data")
                            gapDetected = True

                            
                            for j in range(expected,received_seq_num_int):
                                lostPacket.append(j)

                            lostPacket = self.removeDup(lostPacket)
                            subtracker = received_seq_num_int+1
                            self.logger.info("Added to lost packet" + str(lostPacket))

                    else:
                        self.logger.info("CORRUPTED")

                        zeros = 0000

                        if buffed:
                            return_msg = self.createReturn(expected)
                            self.simulator.u_send(return_msg)
                            self.simulator.u_send(return_msg)

                            self.logger.info("Replying ACK {}".format(expected))
                        
                        if subtracker > expected:
                            lostPacket.append(subtracker)
                        else:
                            lostPacket.append(expected)
                            subtracker = expected
                        
                        lostPacket = self.removeDup(lostPacket)
                        self.logger.info("Corrupted add to lost" + str(lostPacket))

                        gapDetected = True
            except socket.timeout as timeoutException:
                if buffed == True:
                    return_msg = self.createReturn(expected)
                    self.simulator.u_send(return_msg)
                    self.logger.info("Replying ACK {}".format(expected))
                self.logger.info(str(timeoutException))
                pass

        self.logger.info("Writing to file")
        for key,value in sorted(received_packets.items()):
            sys.stdout.write(value)

        sys.exit()




    def checksum(self,seq_num_bin_str,data_bin):
        filled_data = string.join([string.zfill(n, 8) for n in map(lambda s: s[2:], map(bin, data_bin))], '')
        checksum = zlib.adler32(seq_num_bin_str + filled_data) & 0xffffffff
        return checksum
    
    def removeDup(self, x):
        return sorted(list(dict.fromkeys(x)))

    def createReturn(self, x):
        ones = 1111
        ack_seq_num_bin_str="{0:b}".format(x).zfill(32)
        ack_seq_num_bin=bytearray(int(ack_seq_num_bin_str[i:i+8],2) for i in range(0,32,8))
        return_msg = ack_seq_num_bin + struct.pack(">i",ones)
        return return_msg

if __name__ == "__main__":
    # test out BogoReceiver
    rcvr = myReceiver()
    rcvr.receive()
