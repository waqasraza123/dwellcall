from dwellcall.crm.contracts import CrmExportRequest, DeliveryResult


class NoCrmProvider:
    def send(self, request: CrmExportRequest) -> DeliveryResult:
        return DeliveryResult("disabled", "CRM_DISABLED")

    def close(self) -> None:
        pass
