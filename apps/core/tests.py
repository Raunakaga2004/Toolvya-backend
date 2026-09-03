from django.test import Client, TestCase


class CoreEndpointsTest(TestCase):
    def setUp(self) -> None:
        self.client = Client()

    def test_home_endpoint(self) -> None:
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertJSONEqual(
            response.content,
            {
                "success": True,
                "data": {"service": "toolvaya-backend", "status": "ok", "version": "0.1.0"},
            },
        )

    def test_health_endpoint(self) -> None:
        response = self.client.get("/health/")
        self.assertEqual(response.status_code, 200)
        self.assertJSONEqual(response.content, {"success": True, "data": {"status": "ok"}})

