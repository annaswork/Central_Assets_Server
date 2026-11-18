/**
 * Central library reference picker modal/tree for app instances.
 */

(function () {
  window.initLibraryPicker = function (instanceId) {
    const form = document.getElementById("pickerForm");
    if (!form) return;

    form.addEventListener("submit", async function (e) {
      e.preventDefault();

      const selectedCats = Array.from(
        document.querySelectorAll('input[name="category_ids"]:checked')
      ).map((el) => el.value);

      const selectedSubs = Array.from(
        document.querySelectorAll('input[name="sub_category_ids"]:checked')
      ).map((el) => el.value);

      const selectedAssets = Array.from(
        document.querySelectorAll('input[name="asset_ids"]:checked')
      ).map((el) => el.value);

      try {
        const response = await fetch(`/api/v1/app-instances/${instanceId}/references`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            category_ids: selectedCats,
            sub_category_ids: selectedSubs,
            asset_ids: selectedAssets,
          }),
        });

        if (response.ok) {
          window.location.href = `/admin/instances/${instanceId}/content`;
        } else {
          const err = await response.json();
          alert(err.error ? err.error.message : "Failed to add references");
        }
      } catch (err) {
        console.error("Reference selection failed:", err);
      }
    });
  };
})();
