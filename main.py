document.getElementById('storeForm').addEventListener('submit', async (e) => {
    e.preventDefault();
    const btn = document.getElementById('submitBtn');
    btn.disabled = true;
    btn.textContent = 'جاري معالجة البيانات وإنشاء كود الـ QR...';

    const formData = new FormData();
    formData.append('store_name', document.getElementById('store_name').value);
    formData.append('store_url', document.getElementById('store_url').value);
    formData.append('whatsapp_number', document.getElementById('whatsapp_number').value);
    formData.append('agent_notes', document.getElementById('agent_notes').value);
    
    const pdfFile = document.getElementById('pdf_file').files[0];
    if (pdfFile) {
        formData.append('pdf_file', pdfFile);
    }

    try {
        const response = await fetch('/api/register-store', {
            method: 'POST',
            body: formData
        });
        const data = await response.json();

        if (data.status === 'success') {
            document.getElementById('resultBox').classList.remove('hidden');
            document.getElementById('resultMessage').textContent = data.message;
            document.getElementById('widgetCodeOutput').value = data.widget_code;

            const qrContainer = document.getElementById('qrContainer');
            const qrImg = document.getElementById('qrCodeImg');

            if (data.qr_code) {
                qrContainer.classList.remove('hidden');
                qrImg.src = data.qr_code;
            } else {
                qrContainer.classList.remove('hidden');
                qrContainer.innerHTML = '<p class="text-xs text-amber-600 font-semibold py-2">⚠️ لم يتم توليد QR Code. يرجى التأكد من كتابة رقم الواتساب بشكل صحيح وصحة EVOLUTION_GLOBAL_KEY.</p>';
            }
        } else {
            alert('حدث خطأ أثناء التسجيل');
        }
    } catch (error) {
        console.error(error);
        alert('فشل الاتصال بالخادم');
    } finally {
        btn.disabled = false;
        btn.textContent = 'تسجيل وتفعيل المتجر';
    }
});
