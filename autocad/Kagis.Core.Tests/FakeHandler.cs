using System;
using System.Collections.Generic;
using System.Net;
using System.Net.Http;
using System.Text;
using System.Threading;
using System.Threading.Tasks;

namespace Kagis.Core.Tests
{
    /// <summary>Answers HTTP requests from a delegate and records them, so no network is used.</summary>
    internal sealed class FakeHandler : HttpMessageHandler
    {
        private readonly Func<HttpRequestMessage, HttpResponseMessage> _respond;
        public List<HttpRequestMessage> Requests { get; } = new List<HttpRequestMessage>();
        public List<string> Bodies { get; } = new List<string>();

        public FakeHandler(Func<HttpRequestMessage, HttpResponseMessage> respond)
        {
            _respond = respond;
        }

        protected override async Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
        {
            Requests.Add(request);
            Bodies.Add(request.Content == null ? null : await request.Content.ReadAsStringAsync());
            return _respond(request);
        }

        public static HttpResponseMessage Text(string body, HttpStatusCode code = HttpStatusCode.OK) =>
            new HttpResponseMessage(code) { Content = new StringContent(body, Encoding.UTF8, "application/json") };

        public static HttpResponseMessage Bytes(byte[] body, HttpStatusCode code = HttpStatusCode.OK) =>
            new HttpResponseMessage(code) { Content = new ByteArrayContent(body) };

        /// <summary>A minimal little-endian TIFF header followed by filler bytes.</summary>
        public static byte[] TiffBytes(int size = 256)
        {
            var b = new byte[size];
            b[0] = 0x49; b[1] = 0x49; b[2] = 0x2A; b[3] = 0x00;
            return b;
        }
    }
}
