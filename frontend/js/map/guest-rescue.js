function setupGuestRescueUI() {
    const openBtn = document.getElementById('btn-guest-rescue');
    const modalEl = document.getElementById('guestRescueModal');
    if (!openBtn || !modalEl || !window.bootstrap) return;

    window.rescueFormModal = new bootstrap.Modal(modalEl);
    const locateBtn = document.getElementById('btn-guest-rescue-locate');
    const submitBtn = document.getElementById('btn-guest-rescue-submit');
    const imageInput = document.getElementById('guest-rescue-image');
    const imagePreviewWrap = document.getElementById('guest-rescue-image-preview-wrap');
    const imagePreview = document.getElementById('guest-rescue-image-preview');
    const clearImageBtn = document.getElementById('btn-guest-rescue-image-clear');

    const typeRadios = document.querySelectorAll('input[name="guest-rescue-type"]');
    const otherWrap = document.getElementById('guest-rescue-other-wrap');
    if (typeRadios && otherWrap) {
        typeRadios.forEach(radio => {
            radio.addEventListener('change', () => {
                if (radio.value === 'khac' && radio.checked) {
                    otherWrap.style.display = 'block';
                    setTimeout(() => {
                        otherWrap.style.opacity = '1';
                    }, 10);
                } else {
                    otherWrap.style.opacity = '0';
                    setTimeout(() => {
                        if (!document.getElementById('guest-rescue-type-other').checked) {
                            otherWrap.style.display = 'none';
                        }
                    }, 300);
                }
            });
        });
    }

    openBtn.addEventListener('click', () => {
        if (window.rescueFormModal) window.rescueFormModal.show();
        fillGuestRescueLocation();
    });

    if (locateBtn) {
        locateBtn.addEventListener('click', () => fillGuestRescueLocation(true));
    }

    if (submitBtn) {
        submitBtn.addEventListener('click', submitGuestRescueRequest);
    }

    if (imageInput) {
        imageInput.addEventListener('change', async () => {
            const file = imageInput.files?.[0];
            if (!file || !imagePreview || !imagePreviewWrap) {
                return;
            }

            try {
                const blob = await compressImageToBlob(file, 1280, 0.75);
                guestRescueImageBlob = blob;

                if (guestRescueImagePreviewUrl) {
                    URL.revokeObjectURL(guestRescueImagePreviewUrl);
                }
                guestRescueImagePreviewUrl = URL.createObjectURL(blob);
                imagePreview.src = guestRescueImagePreviewUrl;
                imagePreviewWrap.style.display = 'block';
            } catch (e) {
                console.error('compressImageToBlob error:', e);
                window.toast?.error('Không đọc được ảnh. Vui lòng thử ảnh khác.');
            }
        });
    }

    if (clearImageBtn) {
        clearImageBtn.addEventListener('click', () => {
            if (imageInput) {
                imageInput.value = '';
            }
            guestRescueImageBlob = null;
            if (imagePreview) {
                imagePreview.src = '';
            }
            if (guestRescueImagePreviewUrl) {
                URL.revokeObjectURL(guestRescueImagePreviewUrl);
                guestRescueImagePreviewUrl = null;
            }
            if (imagePreviewWrap) {
                imagePreviewWrap.style.display = 'none';
            }
        });
    }

    const searchActionBtn = document.getElementById('btn-guest-rescue-search-address-action');
    const searchInput = document.getElementById('guest-rescue-address-search');
    const searchResults = document.getElementById('guest-rescue-address-results');
    const latEl = document.getElementById('guest-rescue-lat');
    const lonEl = document.getElementById('guest-rescue-lon');

    if (searchActionBtn && searchInput && searchResults) {
        let isSearching = false;

        const performSearch = async () => {
            if (isSearching) return;
            const query = searchInput.value.trim();
            if (!query) return;

            isSearching = true;
            searchActionBtn.innerHTML = '<span class="spinner-border spinner-border-sm"></span>';
            searchResults.style.display = 'block';
            searchResults.innerHTML = '<div class="list-group-item text-muted small text-center"><span class="spinner-border spinner-border-sm me-2"></span>Đang tìm...</div>';

            try {
                const encodedQuery = encodeURIComponent(query + ', Vietnam');
                const url = `https://nominatim.openstreetmap.org/search?format=json&q=${encodedQuery}&limit=5`;
                const response = await fetch(url, {
                    headers: { 'Accept': 'application/json', 'User-Agent': 'LandslideRescueApp/1.0' }
                });
                if (!response.ok) throw new Error('Network response was not ok');
                const data = await response.json();

                if (data && data.length > 0) {
                    searchResults.innerHTML = '';
                    data.forEach(item => {
                        const btn = document.createElement('button');
                        btn.type = 'button';
                        btn.className = 'list-group-item list-group-item-action py-2';
                        const row = document.createElement('div');
                        row.className = 'd-flex align-items-center gap-2';
                        const icon = document.createElement('i');
                        icon.className = 'bi bi-geo-alt-fill text-danger text-opacity-75';
                        icon.setAttribute('aria-hidden', 'true');
                        const copy = document.createElement('div');
                        copy.className = 'rescue-address-result-copy';
                        const title = document.createElement('div');
                        title.className = 'fw-bold text-truncate';
                        title.textContent = String(item.name || 'Địa điểm');
                        const detail = document.createElement('div');
                        detail.className = 'text-muted text-truncate rescue-address-result-detail';
                        detail.textContent = String(item.display_name || '');
                        copy.append(title, detail);
                        row.append(icon, copy);
                        btn.append(row);
                        btn.addEventListener('click', () => {
                            if (latEl) latEl.value = parseFloat(item.lat).toFixed(6);
                            if (lonEl) lonEl.value = parseFloat(item.lon).toFixed(6);
                            searchInput.value = item.display_name;
                            searchResults.style.display = 'none';
                            window.toast?.success('Đã ghim toạ độ từ địa chỉ!');

                            // Optional: Draw marker on map directly
                            if (window.map) {
                                const lat = parseFloat(item.lat);
                                const lon = parseFloat(item.lon);
                                if (window.userLocationMarker) {
                                    window.map.removeLayer(window.userLocationMarker);
                                }
                                if (window.userLocationCircle) {
                                    window.map.removeLayer(window.userLocationCircle);
                                }
                                window.userLocationMarker = L.marker([lat, lon], {
                                    icon: L.divIcon({
                                        className: 'user-location-marker',
                                        html: '<div style="width: 18px; height: 18px; background: #0d6efd; border-radius: 50%; border: 3px solid white; box-shadow: 0 0 15px rgba(13,110,253,0.8); animation: guestRescuePulse 1.5s infinite;"></div>',
                                        iconSize: [18, 18],
                                        iconAnchor: [9, 9]
                                    })
                                }).addTo(window.map).bindPopup('Vị trí đã chọn từ địa chỉ');
                                window.map.setView([lat, lon], 14, { animate: true });
                            }
                        });
                        searchResults.appendChild(btn);
                    });
                } else {
                    searchResults.innerHTML = '<div class="list-group-item text-danger small text-center">Không tìm thấy địa điểm này.</div>';
                }
            } catch (error) {
                console.error('Nominatim search error:', error);
                searchResults.innerHTML = '<div class="list-group-item text-danger small text-center">Lỗi mạng, kiểm tra kết nối internet.</div>';
            } finally {
                isSearching = false;
                searchActionBtn.innerHTML = '<i class="bi bi-search d-none d-sm-inline"></i> Tìm toạ độ';
            }
        };

        searchActionBtn.addEventListener('click', performSearch);
        searchInput.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') {
                e.preventDefault();
                performSearch();
            }
        });

        // Hide results if click outside
        document.addEventListener('click', (e) => {
            if (!searchInput.contains(e.target) && !searchResults.contains(e.target) && !searchActionBtn.contains(e.target)) {
                searchResults.style.display = 'none';
            }
        });
    }
}

async function compressImageToBlob(file, maxWidth = 1280, jpegQuality = 0.75) {
    const fileDataUrl = await new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => resolve(reader.result);
        reader.onerror = reject;
        reader.readAsDataURL(file);
    });

    const img = await new Promise((resolve, reject) => {
        const el = new Image();
        el.onload = () => resolve(el);
        el.onerror = reject;
        el.src = fileDataUrl;
    });

    let targetWidth = img.width;
    let targetHeight = img.height;
    if (img.width > maxWidth) {
        const ratio = maxWidth / img.width;
        targetWidth = maxWidth;
        targetHeight = Math.round(img.height * ratio);
    }

    const canvas = document.createElement('canvas');
    canvas.width = targetWidth;
    canvas.height = targetHeight;
    const ctx = canvas.getContext('2d');
    if (!ctx) {
        throw new Error('Canvas context unavailable');
    }

    ctx.drawImage(img, 0, 0, targetWidth, targetHeight);
    return await new Promise((resolve, reject) => {
        canvas.toBlob((blob) => {
            if (!blob) {
                reject(new Error('Canvas toBlob failed'));
                return;
            }
            resolve(blob);
        }, 'image/jpeg', jpegQuality);
    });
}

function fillGuestRescueLocation(showToast = false) {
    const latEl = document.getElementById('guest-rescue-lat');
    const lonEl = document.getElementById('guest-rescue-lon');
    if (!latEl || !lonEl) return;

    if (!navigator.geolocation) {
        if (showToast) window.toast?.warning('Thiết bị không hỗ trợ GPS');
        return;
    }

    navigator.geolocation.getCurrentPosition(
        (pos) => {
            const lat = pos.coords.latitude;
            const lon = pos.coords.longitude;
            latEl.value = Number(lat).toFixed(7);
            lonEl.value = Number(lon).toFixed(7);
            latEl.dataset.accuracy = Number(pos.coords.accuracy || 0).toFixed(1);
            if (showToast) {
                window.toast?.success(`Đã lấy vị trí (±${latEl.dataset.accuracy}m)`);
            }

            // Vẽ marker cho user location
            if (window.userLocationMarker && window.map) {
                window.map.removeLayer(window.userLocationMarker);
            }
            if (window.userLocationCircle && window.map) {
                window.map.removeLayer(window.userLocationCircle);
            }
            if (window.map) {
                window.userLocationMarker = L.marker([lat, lon], {
                    icon: L.divIcon({
                        className: 'user-location-marker',
                        html: '<div style="width: 18px; height: 18px; background: #0d6efd; border-radius: 50%; border: 3px solid white; box-shadow: 0 0 15px rgba(13,110,253,0.8); animation: guestRescuePulse 1.5s infinite;"></div>',
                        iconSize: [18, 18],
                        iconAnchor: [9, 9]
                    })
                }).addTo(window.map).bindPopup('Vị trí hiện tại của bạn');

                window.userLocationCircle = L.circle([lat, lon], {
                    radius: pos.coords.accuracy,
                    color: '#0d6efd',
                    fillColor: '#0d6efd',
                    fillOpacity: 0.15,
                    weight: 1
                }).addTo(window.map);

                window.map.setView([lat, lon], 14, { animate: true });
            }
        },
        (err) => {
            console.warn('Geolocation error:', err);
            if (showToast) window.toast?.error('Không lấy được vị trí. Hãy bật GPS/quyền vị trí.');
        },
        {
            enableHighAccuracy: true,
            timeout: 12000,
            maximumAge: 15000,
        }
    );
}

async function submitGuestRescueRequest() {
    const nameEl = document.getElementById('guest-rescue-name');
    const phoneEl = document.getElementById('guest-rescue-phone');
    const noteEl = document.getElementById('guest-rescue-note');
    const typeEl = document.querySelector('input[name="guest-rescue-type"]:checked');
    const provinceEl = document.getElementById('guest-rescue-province');
    const sourceLinkEl = document.getElementById('guest-rescue-source-link');
    const imagePreview = document.getElementById('guest-rescue-image-preview');
    const imagePreviewWrap = document.getElementById('guest-rescue-image-preview-wrap');
    const imageInput = document.getElementById('guest-rescue-image');
    const latEl = document.getElementById('guest-rescue-lat');
    const lonEl = document.getElementById('guest-rescue-lon');
    const submitBtn = document.getElementById('btn-guest-rescue-submit');
    if (!nameEl || !phoneEl || !noteEl || !latEl || !lonEl || !submitBtn) return;

    const latitude = parseFloat(latEl.value);
    const longitude = parseFloat(lonEl.value);
    if (!Number.isFinite(latitude) || !Number.isFinite(longitude)) {
        window.toast?.warning('Vui lòng bấm "Lấy vị trí hiện tại" trước khi gửi');
        return;
    }

    let message = String(noteEl.value || '').trim();
    const requesterName = String(nameEl.value || '').trim();
    const phone = String(phoneEl.value || '').trim();
    let rescueType = String(typeEl?.value || 'can_cuu_ho');
    if (rescueType === 'khac') {
        const otherInput = document.getElementById('guest-rescue-other-input');
        if (otherInput && otherInput.value.trim() !== '') {
            rescueType = `Khác: ${otherInput.value.trim()}`;
        }
    }
    const provinceCity = String(provinceEl?.value || '').trim();
    const sourceLink = String(sourceLinkEl?.value || '').trim();

    const searchAddressEl = document.getElementById('guest-rescue-address-search');
    const manualAddressEl = document.getElementById('guest-rescue-address-manual');
    const typedAddress = String(searchAddressEl?.value || '').trim();
    const manualAddress = String(manualAddressEl?.value || '').trim();

    if (manualAddress) {
        message = `[Địa chỉ chi tiết]: ${manualAddress}\n\n${message}`;
    }
    if (typedAddress) {
        message = `[Khu vực vị trí Map]: ${typedAddress}\n${message}`;
    }

    if (!message) {
        window.toast?.warning('Hãy nhập mô tả ngắn tình trạng cần cứu hộ');
        return;
    }

    const oldHtml = submitBtn.innerHTML;
    submitBtn.disabled = true;
    submitBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>Đang gửi...';

    try {
        const formData = new FormData();
        formData.append('requester_name', requesterName);
        formData.append('phone', phone);
        formData.append('message', message);
        formData.append('latitude', String(latitude));
        formData.append('longitude', String(longitude));
        formData.append('accuracy_m', String(Number(latEl.dataset.accuracy || 0) || ''));
        formData.append('rescue_type', rescueType);
        formData.append('province_city', provinceCity);
        formData.append('source_link', sourceLink);
        if (guestRescueImageBlob) {
            formData.append('image_file', guestRescueImageBlob, 'rescue.jpg');
        }

        const res = await fetch('/api/public/rescue-requests', {
            method: 'POST',
            body: formData,
        });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        window.toast?.success('Đã gửi yêu cầu cứu hộ thành công. Admin sẽ kiểm tra ngay.');
        if (window.rescueFormModal) window.rescueFormModal.hide();
        nameEl.value = '';
        phoneEl.value = '';
        noteEl.value = '';
        if (provinceEl) provinceEl.value = '';
        if (sourceLinkEl) sourceLinkEl.value = '';
        const defaultTypeEl = document.getElementById('guest-rescue-type-emergency');
        if (defaultTypeEl) {
            defaultTypeEl.checked = true;
            defaultTypeEl.dispatchEvent(new Event('change'));
        }
        const otherInput = document.getElementById('guest-rescue-other-input');
        if (otherInput) otherInput.value = '';
        if (searchAddressEl) searchAddressEl.value = '';
        const manualAddressEl = document.getElementById('guest-rescue-address-manual');
        if (manualAddressEl) manualAddressEl.value = '';
        guestRescueImageBlob = null;
        if (imagePreview) {
            imagePreview.src = '';
        }
        if (guestRescueImagePreviewUrl) {
            URL.revokeObjectURL(guestRescueImagePreviewUrl);
            guestRescueImagePreviewUrl = null;
        }
        if (imagePreviewWrap) {
            imagePreviewWrap.style.display = 'none';
        }
        if (imageInput) {
            imageInput.value = '';
        }
    } catch (e) {
        console.error('submitGuestRescueRequest error:', e);
        window.toast?.error('Gửi yêu cầu thất bại, vui lòng thử lại.');
    } finally {
        submitBtn.disabled = false;
        submitBtn.innerHTML = oldHtml;
    }
}
