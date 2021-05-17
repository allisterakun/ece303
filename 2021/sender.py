# Written by S. Mevawala, modified by D. Gitzel

import logging
import socket

import time
import struct
import string
import zlib

import channelsimulator
import utils
import sys

class Sender(object):

    def __init__(self, inbound_port=50006, outbound_port=50005, timeout=10, debug_level=logging.INFO):
        self.logger = utils.Logger(self.__class__.__name__, debug_level)

        self.inbound_port = inbound_port
        self.outbound_port = outbound_port
        self.simulator = channelsimulator.ChannelSimulator(inbound_port=inbound_port, outbound_port=outbound_port,
                                                           debug_level=debug_level)
        self.simulator.sndr_setup(timeout)
        self.simulator.rcvr_setup(timeout)

    def send(self, data):
        raise NotImplementedError("The base API class has no implementation. Please override and add your own.")


class BogoSender(Sender):

    def __init__(self):
        super(BogoSender, self).__init__()

    def send(self, data):
        self.logger.info("Sending on port: {} and waiting for ACK on port: {}".format(self.outbound_port, self.inbound_port))
        while True:
            try:
                self.simulator.u_send(data)  # send data
                ack = self.simulator.u_receive()  # receive ACK
                self.logger.info("Got ACK from socket: {}".format(
                    ack.decode('ascii')))  # note that ASCII will only decode bytes in the range 0-127
                break
            except socket.timeout:
                pass

class mySender(BogoSender):

    WINDOW_SIZE=2**11
    BYTES_PER_PACKET=64
    def __init__(self):
        super(mySender, self).__init__()

    def send(self, data):
        self.logger.info("Sending on port: {} and waiting for ACK on port: {}".format(self.outbound_port, self.inbound_port))

        lower=0

        tuple_array,success = self.prepare_data(data)
        total_packets=len(tuple_array)

        window_size=self.WINDOW_SIZE if total_packets > self.WINDOW_SIZE else total_packets

        termination=False

        while ~termination:
            try:
                # upper=lower+window_size if lower+window_size < total_packets else total_packets
                upper=min(lower+window_size,total_packets)

                lower_seq_num_bin = tuple_array[lower]["sequence_number"]
                upper_seq_num_bin = tuple_array[upper-1]["sequence_number"]

                lower_seq_num_int = struct.unpack(">i",lower_seq_num_bin)[0]
                upper_seq_num_int = struct.unpack(">i",upper_seq_num_bin)[0]

                for i in range(lower_seq_num_int,upper_seq_num_int):
                    if tuple_array[i]["sent"] == False:
                        datagram = tuple_array[i]["sequence_number"] + \
                                   tuple_array[i]["data_packet_length"] + \
                                   tuple_array[i]["checksum"] + \
                                   tuple_array[i]["data"]

                        self.simulator.u_send(datagram)
                        tuple_array[i]["sent"]=True
                        self.logger.info("Sent packet with sequence number {}".format(i))
                
                while True:
                    return_packet=self.simulator.u_receive()

                    returned_seq_num_bin=return_packet[0:4]
                    returned_ack_bin=return_packet[4:8]

                    returned_seq_num_int=struct.unpack(">i",returned_seq_num_bin)[0]
                    returned_ack_int=struct.unpack(">i",returned_ack_bin)[0]

                    

                    if  returned_seq_num_int>=lower and returned_seq_num_int<=upper \
                        and success[returned_seq_num_int] == False \
                        and (returned_ack_int==1111 or \
                             returned_ack_int==1110 or \
                             returned_ack_int==1101 or \
                             returned_ack_int==1011 or \
                             returned_ack_int==111):
                        success[returned_seq_num_int]=True
                        self.logger.info("Received ACK for packet with sequence number {}".format(returned_seq_num_int))
                        if returned_seq_num_int==lower:
                            break

                    # find the next unsuccessful packet and update lower
                for i in range(lower,min(upper+1,total_packets-1)):
                    if not success[i]:
                        lower = i
                        break
                    
            except socket.timeout as timeoutException:
                self.logger.info(str(timeoutException))
                unfinished=False
                for i in range(lower_seq_num_int,upper_seq_num_int+1):
                    if not success[i]:
                        datagram = tuple_array[i]["sequence_number"] + \
                                   tuple_array[i]["data_packet_length"] + \
                                   tuple_array[i]["checksum"] + \
                                   tuple_array[i]["data"]
                        self.simulator.u_send(datagram)
                        unfinished=True
                        self.logger.info("Resent packet with sequence number {}".format(i))
                
                if ~unfinished:
                    self.logger.info("Finished")
                    termination=True


        # done with all packets, time for terminator
        while True:
            self.logger.info("Try to terminate")
            try:
                # send "1011111" as termination message
                self.simulator.u_send(bytearray([255, 0] + [255]*5))
                self.logger.info("Sent TERMINATION MESSAGE")
                ack = self.simulator.u_receive()

            except socket.timeout as e:
                self.logger.info(str(e))
            
            # if reciever returns "1011111" -> successful termination
            if ack[0] & (~ack[1] & 0xFF) & ack[2] & ack[3] & ack[4] & ack[5] & ack[6] == 255:
                self.logger.info("Received TERMINATION CONFIRMATION")
                sys.exit()
                break




    def prepare_data(self,data):
        self.logger.info("Preparing data")
        tuple_array=[]
        success={}
        input_length=len(data)
        for i in range(0,input_length/self.BYTES_PER_PACKET+1):
            lower=i*self.BYTES_PER_PACKET
            upper=input_length if lower+self.BYTES_PER_PACKET > input_length else lower+self.BYTES_PER_PACKET

            data_packet_length_int=upper-lower
            data_packet_length_bin=struct.pack(">i",data_packet_length_int & 0xFF) 

            data_packet_content_bin=data[lower:upper] + bytearray([0]*(self.BYTES_PER_PACKET + lower - upper))

            sequence_num_int=i
            sequence_num_bin_str="{0:b}".format(sequence_num_int).zfill(32)
            sequence_num_bin=bytearray(int(sequence_num_bin_str[i:i+8],2) for i in range(0,32,8))

            checksum_bin_str=bin(self.checksum(sequence_num_bin_str,data_packet_content_bin))
            checksum_bin=bytearray(int(checksum_bin_str[i:i+8],2) for i in range(0,32,8)) 

            tuple_array.append({
                "sequence_number":      sequence_num_bin,
                "data_packet_length":   data_packet_length_bin,
                "checksum":             checksum_bin,
                "data":                 data_packet_content_bin,
                "sent":                 False})
            success[i] = False
        
        self.logger.info("Done preparing data")
        return tuple_array,success

    def checksum(self,seq_num_bin_str,data_bin):
        filled_data = string.join([string.zfill(n, 8) for n in map(lambda s: s[2:], map(bin, data_bin))], '')
        checksum = zlib.adler32(seq_num_bin_str + filled_data) & 0xffffffff
        return checksum




if __name__ == "__main__":
    # test out BogoSender
    DATA = bytearray(sys.stdin.read())
    sndr = mySender()
    sndr.send(DATA)
