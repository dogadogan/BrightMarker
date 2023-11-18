using UnityEngine;
using System;
using System.Text;
using System.Net;
using System.Net.Sockets;
using System.Threading;

public class UDPReceive : MonoBehaviour
{
    private bool USE_UNITY_PLAY_MODE = false; // Set to true if you intend to use holographics remoting or Quest Link (i.e. streaming Unity Play Mode to a headset)
    private string IP_ADDRESS = "123.45.67.890"; // Replace with the IP address of the computer sending data to the headset (ignore this if USE_UNITY_PLAY_MODE is true)

    Thread receiveThread;
    UdpClient client; 
    public int port = 5051;
    public bool startRecieving = true;
    public bool printToConsole = false;
    public string data;


    public void Start()
    {
        receiveThread = new Thread(new ThreadStart(ReceiveData));
        receiveThread.IsBackground = true;
        receiveThread.Start();
    }


    // receive thread
    private void ReceiveData()
    {

        client = new UdpClient(port);
        while (startRecieving)
        {

            try
            {
                if (USE_UNITY_PLAY_MODE){
                    IPEndPoint anyIP = new IPEndPoint(IPAddress.Any, 0);
                }
                else {
                    IPEndPoint anyIP = new IPEndPoint(IPAddress.Parse(IP_ADDRESS), 5051);
                }
                byte[] dataByte = client.Receive(ref anyIP);
                data = Encoding.UTF8.GetString(dataByte);
            }
            catch (Exception err)
            {
                print(err.ToString());
            }
        }
    }

}
